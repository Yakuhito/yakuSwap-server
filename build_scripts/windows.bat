echo debug off!
echo false > .debug

echo install python packages
pip install -r requirements.txt

echo install clvm
git clone https://github.com/Chia-Network/clvm.git
cd clvm
pip install -e .
cd ..

echo install clvm_tools
git clone https://github.com/Chia-Network/clvm_tools.git
cd clvm_tools
pip install -e .
cd ..

echo create executable
pip install pyinstaller
pyinstaller -F main.py

echo make windows package
mkdir dist\windows
move dist\main.exe dist\windows\yakuSwap-server.exe
copy contract.clvm dist\windows\contract.clvm

