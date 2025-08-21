"""验证码识别器"""

import os
import logging
import hashlib
import base64
import uuid
from typing import Tuple, Optional
from PIL import Image
import numpy as np
import aiohttp
import io

# 验证码识别方式常量
CAPTCHA_METHOD_NCC = "ncc"
CAPTCHA_METHOD_CHAOJIYING = "chaojiying"

# 超级鹰配置
CHAOJIYING_API_URL = "https://upload.chaojiying.net/Upload/Processing.php"
CHAOJIYING_CODETYPE = "6001"  # 计算题，他比俩个汉字的单价便宜(计算题15，汉字是20)，测试了一次发现也可以识别

_LOGGER = logging.getLogger(__name__)


class NCCCaptchaRecognizer:
    """基于NCC算法的验证码识别器"""

    def __init__(self):
        """初始化NCC识别器"""
        self._templates = {}
        self._templates_dir = os.path.join(os.path.dirname(__file__), "templates")
        self._confidence_threshold = 0.35
        self._templates_loaded = False

    async def _load_templates(self):
        """加载模板文件"""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        if not os.path.exists(self._templates_dir):
            _LOGGER.warning(f"模板目录不存在: {self._templates_dir}")
            return

        def load_single_template(filename):
            """加载单个模板文件"""
            if not filename.endswith(".png"):
                return None

            # 模板文件名格式: char_name_uuid.png
            parts = os.path.splitext(filename)[0].split("_")
            if len(parts) < 2:
                return None

            char_name = parts[0]
            template_path = os.path.join(self._templates_dir, filename)
            try:
                with open(template_path, "rb") as f:
                    img = Image.open(f)
                    img.load()  # 确保图片数据被加载
                    template_binary = self._get_binary_image(img)
                    if template_binary is not None:
                        return (char_name, template_binary)
            except Exception as e:
                _LOGGER.warning(f"无法加载模板文件 {template_path}: {e}")
            return None

        # 获取所有模板文件
        def list_template_files():
            """在线程中列出模板文件"""
            try:
                return os.listdir(self._templates_dir)
            except OSError as e:
                _LOGGER.error(f"无法读取模板目录 {self._templates_dir}: {e}")
                return []

        loop = asyncio.get_event_loop()
        filenames = await loop.run_in_executor(None, list_template_files)

        # 使用线程池异步加载模板
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=4) as executor:
            tasks = [
                loop.run_in_executor(executor, load_single_template, filename)
                for filename in filenames
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
        template_count = 0
        for result in results:
            if isinstance(result, Exception):
                _LOGGER.warning(f"加载模板时出现异常: {result}")
                continue
            if result is not None:
                char_name, template_binary = result
                if char_name not in self._templates:
                    self._templates[char_name] = []
                self._templates[char_name].append(template_binary)
                template_count += 1

        _LOGGER.info(
            f"加载了 {template_count} 个模板，覆盖 {len(self._templates)} 个字符"
        )

    def _get_binary_image(self, pil_image, threshold=127):
        """将PIL图片转换为二值化numpy数组"""
        img_gray = pil_image.convert("L")
        img_array = np.array(img_gray)
        binary_img = (img_array < threshold).astype(np.uint8)
        return binary_img

    def _normalized_cross_correlation(self, template, image):
        """使用 numpy 实现 NCC 算法"""
        try:
            # 统一模板和图像尺寸
            resized_image = np.array(
                Image.fromarray(image * 255).resize(template.shape[::-1], Image.LANCZOS)
            )
            resized_image = (resized_image < 127).astype(np.uint8)

            T = template.astype(float)
            I = resized_image.astype(float)
            T_centered = T - np.mean(T)
            I_centered = I - np.mean(I)
            numerator = np.sum(T_centered * I_centered)
            denominator = np.sqrt(np.sum(T_centered**2) * np.sum(I_centered**2))
            if denominator == 0:
                return 0
            return numerator / denominator
        except Exception:
            return 0

    def _segment_by_center(self, binary_img):
        """使用图片中线进行分割"""
        height, width = binary_img.shape
        mid_point = width // 2

        char1_img = binary_img[:, :mid_point]
        char2_img = binary_img[:, mid_point:]

        # 简单检查分割后的区域是否包含字符像素
        if np.sum(char1_img) == 0 or np.sum(char2_img) == 0:
            return []

        # 找到每个分割区域的精确边界框
        def get_bbox(segment):
            coords = np.argwhere(segment > 0)
            if coords.size == 0:
                return None
            y1, x1 = coords.min(axis=0)
            y2, x2 = coords.max(axis=0)
            return (x1, y1, x2, y2)

        box1 = get_bbox(char1_img)
        box2 = get_bbox(char2_img)

        if box1 and box2:
            return [
                (box1[0], box1[1], box1[2], box1[3]),
                (box2[0] + mid_point, box2[1], box2[2] + mid_point, box2[3]),
            ]

        return []

    def _extract_char_images(self, binary_img, bboxes):
        """根据边界框提取单个字符图像"""
        char_images = []
        for x1, y1, x2, y2 in bboxes:
            char_img = binary_img[y1 : y2 + 1, x1 : x2 + 1]
            char_images.append(char_img)
        return char_images

    async def recognize(self, image_data: bytes) -> Tuple[str, float]:
        """识别验证码

        Args:
            image_data: 验证码图片的二进制数据

        Returns:
            (识别结果, 平均置信度)
        """
        # 确保模板已加载
        if not self._templates_loaded:
            await self._load_templates()
            self._templates_loaded = True

        if not self._templates:
            raise RuntimeError("没有可用的模板文件")

        try:
            # 加载图片
            img = Image.open(io.BytesIO(image_data))
            binary_img = self._get_binary_image(img)

            # 分割字符
            bboxes = self._segment_by_center(binary_img)
            if len(bboxes) != 2:
                raise RuntimeError("无法正确分割验证码图片")

            char_images = self._extract_char_images(binary_img, bboxes)

            # 识别每个字符
            recognized_text = ""
            confidences = []

            for char_img in char_images:
                best_match = ""
                max_score = -1.0

                for char_name, template_list in self._templates.items():
                    for template in template_list:
                        score = self._normalized_cross_correlation(template, char_img)
                        if score > max_score:
                            max_score = score
                            best_match = char_name

                confidences.append(max_score)
                recognized_text += best_match

            avg_confidence = sum(confidences) / len(confidences) if confidences else 0

            _LOGGER.debug(
                f"NCC识别结果: {recognized_text}, 置信度: {confidences}, 平均: {avg_confidence:.3f}"
            )

            return recognized_text, avg_confidence

        except Exception as e:
            _LOGGER.error(f"NCC验证码识别失败: {e}")
            raise

    def is_available(self) -> bool:
        """检查识别器是否可用"""
        # 如果模板还没加载，简单检查模板目录是否存在
        if not self._templates_loaded:
            return os.path.exists(self._templates_dir)
        return len(self._templates) > 0


class ChaoJiYingCaptchaRecognizer:
    """超级鹰验证码识别器"""

    def __init__(self, username: str, password: str, soft_id: str):
        """初始化超级鹰识别器

        Args:
            username: 超级鹰用户名
            password: 超级鹰密码
            soft_id: 软件ID
        """
        self.username = username
        self.password = password
        self.soft_id = soft_id

    def _md5(self, text: str) -> str:
        """计算MD5"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    async def recognize(self, image_data: bytes) -> Tuple[str, float]:
        """识别验证码

        Args:
            image_data: 验证码图片的二进制数据

        Returns:
            (识别结果, 置信度)
        """
        try:
            # 准备请求数据
            data = aiohttp.FormData()
            data.add_field("user", self.username)
            data.add_field("pass2", self._md5(self.password))
            data.add_field("softid", self.soft_id)
            data.add_field("codetype", CHAOJIYING_CODETYPE)
            data.add_field(
                "userfile", image_data, filename="captcha.png", content_type="image/png"
            )

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    CHAOJIYING_API_URL, data=data, timeout=30
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(f"超级鹰API请求失败: {response.status}")

                    result = await response.json()

                    if result.get("err_no") == 0:
                        pic_str = result.get("pic_str", "")
                        if len(pic_str) == 2:  # 确保返回2个字符
                            _LOGGER.debug(f"超级鹰识别成功: {pic_str}")
                            return pic_str, 0.9  # 超级鹰API通常有较高准确率
                        else:
                            raise RuntimeError(f"超级鹰返回结果长度不正确: {pic_str}")
                    else:
                        error_msg = result.get("err_str", "未知错误")
                        raise RuntimeError(f"超级鹰识别失败: {error_msg}")

        except Exception as e:
            _LOGGER.error(f"超级鹰验证码识别失败: {e}")
            raise

    def is_available(self) -> bool:
        """检查识别器是否可用"""
        return bool(self.username and self.password and self.soft_id)


class CaptchaRecognizer:
    """验证码识别器统一接口"""

    def __init__(self, method: str = CAPTCHA_METHOD_NCC, **kwargs):
        """初始化识别器

        Args:
            method: 识别方法 (ncc 或 chaojiying)
            **kwargs: 其他参数
        """
        self.method = method
        self._recognizer = None

        if method == CAPTCHA_METHOD_NCC:
            self._recognizer = NCCCaptchaRecognizer()
        elif method == CAPTCHA_METHOD_CHAOJIYING:
            username = kwargs.get("username")
            password = kwargs.get("password")
            soft_id = kwargs.get("soft_id")
            if not all([username, password, soft_id]):
                raise ValueError("超级鹰识别器需要提供 username, password, soft_id")
            self._recognizer = ChaoJiYingCaptchaRecognizer(username, password, soft_id)
        else:
            raise ValueError(f"不支持的识别方法: {method}")

    async def recognize(self, image_data: bytes) -> Tuple[str, float]:
        """识别验证码

        Args:
            image_data: 验证码图片的二进制数据

        Returns:
            (识别结果, 置信度)
        """
        if not self._recognizer:
            raise RuntimeError("识别器未初始化")

        return await self._recognizer.recognize(image_data)

    def is_available(self) -> bool:
        """检查识别器是否可用"""
        return self._recognizer and self._recognizer.is_available()

    def get_method(self) -> str:
        """获取识别方法"""
        return self.method
