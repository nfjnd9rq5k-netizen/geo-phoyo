"""Fix .so compression in APK — les .so doivent etre ZIP_STORED (non compresses)."""
import zipfile
import sys

if len(sys.argv) != 3:
    print("Usage: python fix_so.py input.apk output.apk")
    sys.exit(1)

with zipfile.ZipFile(sys.argv[1], 'r') as zin, zipfile.ZipFile(sys.argv[2], 'w') as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename.endswith('.so'):
            item.compress_type = zipfile.ZIP_STORED
        zout.writestr(item, data)

print(f"Fixed: {sys.argv[1]} -> {sys.argv[2]}")
