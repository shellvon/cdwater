"""
此脚本是我迫于无奈之选， 当我想要把成都的 水、电、气 同时接入Hass我找不到一个可以在我nano-pi 500M 内存 7G磁盘上跑的解决方案
模型是没有机会了，要么是硬件不兼容（比如onnxruntime无法安装）、要么就是贼吃资源。

一种可能的方式是使用云端API来实现，比如超级鹰。但我偏偏想要一分钱也不愿意花把这个事情给办了，所以我不得不把水电气内用到的验证码采用更为传统的方式实现。
使其可以在我本地极小的资源上解决掉验证码的问题，幸运的是，我曾经在国家电网处理验证码的时候 NCC 的经验让我觉得水费也可以如此处理。但问题是，
成都自来水的短信验证码是汉字，汉字那么多怎么办? 我没有这么多汉字模版，而且简单看了几次发现字体似乎是2种。这就得double！

但幸运的是，我在检索的时候发现了这个论坛: https://bbs.hassbian.com/thread-21847-1-1.html 查看了对应的地址
显示验证码的汉字似乎是有限的某些字，这就好办了，当模版足够少，且拆分也很明确的情况下，我们只需要准备好模版就好了

成都自来水的验证码很简单的地方在于，他一定是固定的2个汉字，且汉字之间没有旋转、干扰线、甚至选择的汉字有限。所以我们可以直接按照长度/2 就可以拆出来2个汉字
最初，我以为一个汉字最多2个模版就好了（字体似乎俩种），但实际我发现模版太少的情况下，识别率很差。我不得不修改脚本，从而让一个汉字可以产生多个模版。
因此，有了目前的这个脚本，这个脚本其实会尝试随机下载一个验证码，由人工确定拆分之后保存，对于置信度很高且识别正确的汉字就不会再保存，否则会额外保存
后续在识别NCC的时候，我们只需要提前加载这些模版，然后尝试批量匹配就好，具体的代码可以参考 captcha.py

经过了一天的努力，此脚本可能有个50%+的识别率( 加载了 244 个模板，覆盖 84 个字符)就暂时这样吧! 够我用了

2025-08-21 05:32:44.655 INFO (MainThread) [custom_components.cdwater.captcha] 加载了 244 个模板，覆盖 84 个字符
2025-08-21 05:32:44.990 INFO (MainThread) [custom_components.cdwater.client] 解析结果: 水费账单 6 条, 垃圾费 12 条, 水费欠费 0 条, 垃圾费欠费 1 条
2025-08-21 05:32:44.990 INFO (MainThread) [custom_components.cdwater.client] 第 1 次尝试成功，验证码: 井开, 置信度: 0.531
"""

import aiohttp
import asyncio
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import os
import io
import sys
import uuid

TEMPLATES_DIR = "templates"
TEST_RESULTS_DIR = "test_results"
CAPTCHA_URL = "https://www.cdwater.com.cn/record_{}.html"
CONFIDENCE_THRESHOLD = 0.35  # 置信度阈值


def normalized_cross_correlation(template, image):
    """使用 numpy 实现 NCC 算法"""
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


async def get_image_from_url(session, url):
    """异步从URL下载图片并返回PIL对象"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
        }
        async with session.get(url, headers=headers, timeout=10) as response:
            response.raise_for_status()
            content = await response.read()
            return Image.open(io.BytesIO(content))
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"Error downloading image from {url}: {e}")
        return None


def get_binary_image(pil_image, threshold=127):
    """将PIL图片转换为二值化numpy数组"""
    img_gray = pil_image.convert("L")
    img_array = np.array(img_gray)
    binary_img = (img_array < threshold).astype(np.uint8)
    return binary_img


def segment_by_center(binary_img):
    """
    使用图片中线进行分割
    """
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


def extract_char_images(binary_img, bboxes):
    """根据边界框提取单个字符图像"""
    char_images = []
    for x1, y1, x2, y2 in bboxes:
        char_img = binary_img[y1 : y2 + 1, x1 : x2 + 1]
        char_images.append(char_img)
    return char_images


def load_templates():
    """加载所有模板，包括多个版本"""
    templates = {}
    if not os.path.isdir(TEMPLATES_DIR):
        os.makedirs(TEMPLATES_DIR)
        print(f"Created directory: {TEMPLATES_DIR}")

    for filename in os.listdir(TEMPLATES_DIR):
        if filename.endswith(".png"):
            # 模板文件名格式: char_name_uuid.png
            parts = os.path.splitext(filename)[0].split("_")
            char_name = parts[0]
            template_path = os.path.join(TEMPLATES_DIR, filename)
            try:
                template_binary = get_binary_image(Image.open(template_path))
                if template_binary is not None:
                    if char_name not in templates:
                        templates[char_name] = []
                    templates[char_name].append(template_binary)
            except IOError:
                print(f"Warning: Could not open template file: {template_path}")
    return templates


async def build_mode():
    """模式1: 智能模板生成 - 先尝试识别，再决定是否更新"""
    print("\n--- [Build Mode] ---")
    print("Welcome to smart template building mode.")
    print("Type 'q' to quit at any time.")

    templates = load_templates()
    print(
        f"Loaded {sum(len(v) for v in templates.values())} templates for {len(templates)} unique characters."
    )

    async with aiohttp.ClientSession() as session:
        while True:
            confirm = input("Press Enter to download a new captcha, or 'q' to quit: ")
            if confirm.lower() == "q":
                break

            url = CAPTCHA_URL.format(np.random.rand())
            img = await get_image_from_url(session, url)
            if img is None:
                continue

            temp_img_path = "temp_captcha.png"
            img.save(temp_img_path)

            print(
                f"\nSaved a new captcha to '{temp_img_path}'. Please open and view it."
            )

            binary_img = get_binary_image(img)
            bboxes = segment_by_center(binary_img)

            if len(bboxes) != 2:
                print("Could not split the image into two characters. Skipping.")
                os.remove(temp_img_path)
                continue

            char_images = extract_char_images(binary_img, bboxes)

            # 尝试识别
            recognized_text = ""
            confidences = []

            for char_img in char_images:
                best_match = ""
                max_score = -1.0

                for char_name, template_list in templates.items():
                    for template in template_list:
                        try:
                            score = normalized_cross_correlation(template, char_img)
                        except Exception as e:
                            continue

                        if score > max_score:
                            max_score = score
                            best_match = char_name

                confidences.append(max_score)
                # 无论置信度高低，都输出最可能的匹配
                recognized_text += best_match

            print(f"Auto-recognized: {recognized_text} with confidences: {confidences}")

            user_input = input(
                f"Enter the correct two characters (e.g., '时刻'), or 'ok' if auto-recognized is correct, or 'q' to quit: "
            )

            if user_input.lower() == "q":
                os.remove(temp_img_path)
                break

            if user_input.lower() == "ok":
                # 如果用户确认正确，检查是否有低置信度的字符并更新
                for i, (recog_char, conf) in enumerate(
                    zip(recognized_text, confidences)
                ):
                    if conf < CONFIDENCE_THRESHOLD:
                        char_name = recog_char
                        char_img = char_images[i]
                        unique_id = str(uuid.uuid4())
                        template_path = os.path.join(
                            TEMPLATES_DIR, f"{char_name}_{unique_id}.png"
                        )
                        pil_img_template = Image.fromarray(
                            (char_img * 255).astype(np.uint8), mode="L"
                        )
                        pil_img_template.save(template_path)
                        print(f"Template for '{char_name}' saved to {template_path}")

                if all(c >= CONFIDENCE_THRESHOLD for c in confidences):
                    print("Recognition confident. Skipping template update.")
                else:
                    print(
                        "Recognition correct but low confidence. Updating templates for low-conf chars."
                    )

                templates = load_templates()  # 重新加载模板以更新
                os.remove(temp_img_path)
                continue

            if len(user_input) == 2:
                correct_chars = list(user_input)
                print("User corrected. Updating templates for specified chars.")

                for i, (recog_char, correct_char) in enumerate(
                    zip(recognized_text, correct_chars)
                ):
                    # 如果用户输入与识别结果不同，或者置信度低于阈值，则更新模板
                    if (
                        recog_char != correct_char
                        or confidences[i] < CONFIDENCE_THRESHOLD
                    ):
                        char_name = correct_char
                        char_img = char_images[i]
                        unique_id = str(uuid.uuid4())
                        template_path = os.path.join(
                            TEMPLATES_DIR, f"{char_name}_{unique_id}.png"
                        )

                        pil_img_template = Image.fromarray(
                            (char_img * 255).astype(np.uint8), mode="L"
                        )
                        pil_img_template.save(template_path)

                        print(f"Template for '{char_name}' saved to {template_path}")
                        templates = load_templates()

            else:
                print("Invalid input. Skipping.")

            os.remove(temp_img_path)


async def test_mode():
    """模式2: 自动测试 - 识别失败时让用户纠正并更新模板"""
    print("\n--- [Test Mode] ---")
    templates = load_templates()
    if not templates:
        print(
            "No templates found. Please run build mode first to create your template library."
        )
        return

    print(
        f"Loaded {sum(len(v) for v in templates.values())} templates for {len(templates)} unique characters."
    )

    num_tests = 10
    recognized_count = 0

    if not os.path.exists(TEST_RESULTS_DIR):
        os.makedirs(TEST_RESULTS_DIR)

    async with aiohttp.ClientSession() as session:
        for i in range(num_tests):
            url = CAPTCHA_URL.format(np.random.rand())
            img = await get_image_from_url(session, url)
            if img is None:
                continue

            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("arial.ttf", 15)
            except IOError:
                font = ImageFont.load_default()

            binary_img = get_binary_image(img)
            bboxes = segment_by_center(binary_img)

            recognized_text = ""
            confidences = []

            if len(bboxes) == 2:
                char_images = extract_char_images(binary_img, bboxes)

                for char_img in char_images:
                    best_match = ""
                    max_score = -1.0

                    for char_name, template_list in templates.items():
                        for template in template_list:
                            try:
                                score = normalized_cross_correlation(template, char_img)
                            except Exception as e:
                                continue

                            if score > max_score:
                                max_score = score
                                best_match = char_name

                    confidences.append(max_score)
                    recognized_text += best_match

            # 保存结果图片
            unique_filename = str(uuid.uuid4())
            result_path = os.path.join(
                TEST_RESULTS_DIR, f"{recognized_text}_{unique_filename}.png"
            )
            img.save(result_path)

            print(
                f"Test {i+1}: URL: {url} -> Recognized: {recognized_text} with confidences: {confidences}, saved to {result_path}"
            )

            if any(c < CONFIDENCE_THRESHOLD for c in confidences):
                # 识别失败或低置信，让用户纠正
                user_input = input(
                    f"Recognition uncertain. Enter correct two characters (e.g., '时刻'), or 'skip' to continue without update: "
                )
                if user_input.lower() == "skip":
                    continue
                if len(user_input) == 2:
                    correct_chars = list(user_input)
                    for j in range(2):
                        if (
                            recognized_text[j] != correct_chars[j]
                            or confidences[j] < CONFIDENCE_THRESHOLD
                        ):
                            char_name = correct_chars[j]
                            char_img = char_images[j]
                            unique_id = str(uuid.uuid4())
                            template_path = os.path.join(
                                TEMPLATES_DIR, f"{char_name}_{unique_id}.png"
                            )

                            pil_img_template = Image.fromarray(
                                (char_img * 255).astype(np.uint8), mode="L"
                            )
                            pil_img_template.save(template_path)

                            print(
                                f"Template for '{char_name}' saved to {template_path}"
                            )
                            templates = load_templates()
                else:
                    print("Invalid input. Skipping update.")
            else:
                recognized_count += 1

    print(f"\n--- Test Summary ---")
    print(f"Total tests: {num_tests}")
    print(f"Successfully recognized (high confidence): {recognized_count}")
    print(f"Accuracy: {recognized_count / num_tests:.2%}")


async def main():
    if not os.path.exists(TEMPLATES_DIR):
        os.makedirs(TEMPLATES_DIR)
    if not os.path.exists(TEST_RESULTS_DIR):
        os.makedirs(TEST_RESULTS_DIR)

    while True:
        print("\n--- OCR CLI Main Menu ---")
        print("1. Build Templates (smart interactive)")
        print("2. Run Automated Tests (with correction)")
        print("3. Exit")

        choice = input("Enter your choice (1-3): ")

        if choice == "1":
            await build_mode()
        elif choice == "2":
            await test_mode()
        elif choice == "3":
            print("Exiting...")
            break
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")


if __name__ == "__main__":
    if sys.version_info >= (3, 7):
        asyncio.run(main())
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
