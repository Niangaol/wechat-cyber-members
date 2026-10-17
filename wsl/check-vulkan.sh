#!/bin/bash
echo "=== 装 vulkan-tools 并查设备 ==="
sudo apt-get install -y -qq vulkan-tools >/dev/null 2>&1 && echo "installed"
vulkaninfo --summary 2>&1 | grep -A12 "Devices:" | head -16
echo "=== GPU 在 Vulkan 里的名字 ==="
vulkaninfo --summary 2>&1 | grep -iE "deviceName|apiVersion" | head -6
