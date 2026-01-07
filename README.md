# Slide Mobile Manager

A simple Flask-based remote slide controller for presentations, with QR code access for mobile devices.

## Requirements
- Python 3.8+
- pip (Python package manager)

## Installation
1. Install dependencies:

```powershell
pip install flask pyautogui qrcode
```

2. (Optional) If you want to build a standalone Windows executable:

```powershell
pip install pyinstaller
```

## Running the App (with Console)

### Option 1: Run with Python (recommended for development)

```powershell
python app.py
```

### Option 2: Build and run as a Windows executable (with console)

1. Build the executable:

```powershell
py -m PyInstaller --onefile app.py
```

2. Run the generated executable:

```powershell
./dist/app.exe
```

## Usage
- After starting the app, scan the QR code or open the provided URL on your mobile device.
- Use the on-screen buttons to control your presentation slides remotely.

## Notes
- Make sure your computer and mobile device are on the same network.
- If you rebuild the executable and get a permission error, close all running instances of `app.exe` first.
