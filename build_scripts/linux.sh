#!/bin/bash

# debug off!
echo false > .debug

# install python packages
pip install -r requirements.txt

# install clvm
git clone https://github.com/Chia-Network/clvm.git
cd clvm
pip install -e .
cd ..

# install clvm_tools
git clone https://github.com/Chia-Network/clvm_tools.git
cd clvm_tools
pip install -e .
cd ..

# create executable
pip install pyinstaller
pyinstaller -F main.py

# package
mkdir dist/linux
mv dist/main dist/linux/yakuSwap
cp contract.clvm dist/linux/contract.clvm
cp networks.json dist/linux/networks.json
