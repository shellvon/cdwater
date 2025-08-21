# 成都自来水 Home Assistant 集成

这是一个用于 Home Assistant 的成都自来水集成插件，可以自动获取水费账单和垃圾处理费信息。

## 原理

成都自来水在有户号的情况下，没有复杂的授权等逻辑, 可以直接在这里查询: https://www.cdwater.com.cn/htm/waterbill.html

本集成就是在拿到用户配置的户号之后，自动识别验证码并且将网页 HTML 表格解析成 json 格式，然后利用 hass 将其集成到传感器上展示

## 功能特性

- 自动获取水费账单数据
- 自动获取垃圾处理费数据
- 支持欠费信息查询
- 支持两种验证码识别方式：
  - **NCC 算法**：传统的模板匹配算法，免费但识别率较低
  - **超级鹰 API**：在线识别服务，准确率高但需要付费账号
- 自动重试机制（最多 3 次）
- 可配置的数据更新间隔

## 安装方法

### 通过 HACS 安装（推荐）

1. 确保已安装 [HACS](https://hacs.xyz/)
2. 在 HACS 中添加自定义存储库：
   - 进入 HACS → 集成
   - 点击右上角三个点 → 自定义存储库
   - 添加存储库 URL：`https://github.com/shellvon/cdwater`
   - 类别选择：集成
3. 搜索"成都自来水"并安装
4. 重启 Home Assistant

### 手动
1. 将custom_components下的所有内容复制到 Home Assistant 的 `custom_components` 目录下
2. 重启 Home Assistant
3. 在集成页面添加"成都自来水"集成

## 配置说明

### 基本配置

1. **用户号**：输入您的成都自来水用户号（纯数字）

### 验证码识别配置

#### NCC 算法（推荐新手使用）

- **优点**：免费，本地贼快，无需额外配置
- **缺点**：识别率较低（约 50%+，我猜的），需要模板文件
- **配置**：选择"NCC 算法"即可，无需其他配置

#### 超级鹰 API（推荐高级用户）

- **优点**：识别率高（90%+），稳定可靠
- **缺点**：需要付费账号，每次识别消耗积分
- **配置步骤**：
  1. 注册超级鹰账号：https://www.chaojiying.com/
  2. 充值积分（建议先充值少量测试）
  3. 在用户中心获取软件 ID
  4. 在集成配置中选择"超级鹰 API"
  5. 输入用户名、密码和软件 ID

## NCC 算法模板文件

如果使用 NCC 算法，需要在 `templates` 目录下放置模板文件。模板文件命名格式：`字符_UUID.png`

例如：

- `一_189e1cb8-af9b-4fc3-8332-bbb51781bdac.png`
- `二_43bc95cf-a5cd-40ad-b101-6f3139fb88ae.png`

### 生成模板文件

可以使用提供的 `ncc_template_builder.py` 脚本来生成模板文件：

```bash
python ncc_template_builder.py
```

该脚本提供两种模式：

1. **Build Mode**：智能模板生成模式
2. **Test Mode**：自动测试模式

## 传感器说明

集成会创建以下传感器：

- `sensor.cdwater_[用户号]_latest_water_bill`：最新水费账单
- `sensor.cdwater_[用户号]_latest_garbage_fee`：最新垃圾处理费
- `sensor.cdwater_[用户号]_total_arrears`：总欠费金额

## 故障排除

### 验证码识别失败

1. **NCC 算法**：

   - 检查 `templates` 目录是否存在模板文件
   - 运行 `ncc_template_builder.py` 生成更多模板文件
   - 考虑切换到超级鹰 API

2. **超级鹰 API**：
   - 检查账号余额是否充足
   - 验证用户名、密码、软件 ID 是否正确
   - 检查网络连接

### 查询失败

- 检查用户号是否正确
- 检查网络连接
- 查看 Home Assistant 日志获取详细错误信息

### 重试机制

插件内置 3 次重试机制，如果验证码识别失败会自动重试。可以在日志中看到重试过程。

## 配置选项

在集成的选项中可以配置：

1. **更新间隔**：数据更新周期（1-7 天）
2. **验证码识别设置**：可以重新配置验证码识别方式

## 开发和测试

### 日志调试

在 Home Assistant 的 `configuration.yaml` 中添加：

```yaml
logger:
  logs:
    custom_components.cdwater: debug
```

## 注意事项

1. 请合理设置更新间隔，避免频繁请求， 自来水貌似一个月才更新一次....
2. NCC 算法识别率较低，建议配合重试机制使用
3. 超级鹰 API 按次收费，请注意账户余额
4. 验证码图片可能会变化，NCC 算法需要定期更新模板
