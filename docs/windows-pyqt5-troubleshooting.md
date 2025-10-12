# Windows 图形界面运行时报 `ImportError: DLL load failed while importing QtCore`

当在 Windows 上运行 `gui.py` 时出现如下报错：

```
ImportError: DLL load failed while importing QtCore: 找不到指定的程序。
```

通常表示 Python 找不到 PyQt5 依赖的动态链接库，或安装的 PyQt5 与当前 Python 版本/架构不匹配。下面提供排查步骤。

## 1. 确认 Python 与 pip 指向的环境

在 **同一个命令行** 中依次运行：

```powershell
python --version
where python
python -m pip --version
```

确保输出的路径一致。例如都指向 `C:\Users\<用户名>\AppData\Local\Programs\Python\Python311\`. 如果你安装了多个 Python 版本，需要在正确的环境中安装 PyQt5。

## 2. 重新安装匹配版本的 PyQt5

1. 先升级 pip，避免旧版本无法拉取新 wheel：

   ```powershell
   python -m pip install --upgrade pip
   ```

2. 再重新安装 PyQt5 及其依赖：

   ```powershell
   python -m pip install --force-reinstall "PyQt5==5.15.10" "PyQt5-Qt5==5.15.2.3" "PyQt5-sip==12.13.0"
   ```

   - `5.15.10` 是当前兼容 Python 3.8~3.12 的官方版本；
   - `PyQt5-Qt5` 和 `PyQt5-sip` 会一并安装 Qt 二进制及核心依赖，防止缺失 DLL。

若你使用的是 Python 3.7 或更老版本，可将 `5.15.10` 替换为 `5.15.7`（最后一个支持 3.7 的版本）。

## 3. 检查系统缺失的 VC++ 运行库

PyQt5 依赖 Visual C++ 运行库。若系统未安装，会出现 “找不到指定的程序” 的 DLL 错误。可以从微软官网下载并安装 **Microsoft Visual C++ 2015-2022 Redistributable (x64/x86)**：

- [官方下载页面](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

根据你的 Python 架构选择 x64 或 x86 安装包（可同时装两个）。

## 4. 确认没有缺失的 Qt DLL

安装完成后，确认以下目录存在并包含大量 DLL 文件（`Qt5Core.dll`、`Qt5Gui.dll` 等）：

```
C:\Users\<用户名>\AppData\Local\Programs\Python\Python311\Lib\site-packages\PyQt5\Qt5\bin
```

若目录存在但仍报错，可以把它临时加入环境变量 `PATH`，然后再运行脚本：

```powershell
$env:PATH = "C:\\Users\\<用户名>\\AppData\\Local\\Programs\\Python\\Python311\\Lib\\site-packages\\PyQt5\\Qt5\\bin;" + $env:PATH
python gui.py
```

## 5. 仍无法解决？

- 尝试创建一个全新的虚拟环境：

  ```powershell
  python -m venv .venv
  .\.venv\Scripts\activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt PyQt5==5.15.10
  python gui.py
  ```

- 或使用 [PySide6](https://pypi.org/project/PySide6/) 替代（需修改 `gui.py` 的导入）。

按照以上步骤大多数 DLL 缺失的问题都能解决。如仍遇到困难，可将 `python -m PyQt5.Qt` 的完整报错复制出来，便于进一步定位。
