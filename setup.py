from setuptools import setup

APP = ['musictergym_claude_2slider.py']
DATA_FILES = [
    'titleimg.png',
    'Gym_rat.csv',
]
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'icon.icns',
    'plist': {
        'CFBundleName': 'MusicTerGYM',
        'CFBundleDisplayName': 'MusicTerGYM',
        'CFBundleIdentifier': 'com.hongsangkwon.musictergym',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSMinimumSystemVersion': '12.0',
    },
    'packages': ['requests'],
    'excludes': [
        'numpy', 'pandas', 'scipy', 'matplotlib',
        'PIL', 'PyQt5', 'wx', 'email', 'html',
        'http', 'urllib', 'xml', 'xmlrpc',
        'unittest', 'distutils', 'setuptools',
    ],
    'strip': True,
    'optimize': 2,
}

setup(
    app=APP,
    name='MusicTerGYM',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)