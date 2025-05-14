# Linux HWINFO64

## Requirements
- `nvidia-smi` for Nvidia GPUs
- `rocm-smi` for AMD GPUs

Written in Python


## GPU Detection
It first checks for NVIDIA GPUs using nvidia-smi
Then it checks for AMD GPUs by:
Looking at vendor ID in `/sys/class/drm/card0/device/vendor`
Using `lspci` to search for AMD graphics adapters


## Usage Notes:

For AMD GPUs, some metrics might not be available depending on your specific card and drivers:

Temperature reading paths can vary between different AMD cards
Memory usage requires ROCm tools to be installed
GPU utilization might not be available on older cards/drivers

![Screenshot of the tool running in the terminal](assets/linux_hw_monitor_screenshot.png)


Additional requirements for AMD GPU support:

For basic detection: standard Linux utilities like lspci
For more detailed metrics: AMD's ROCm tools (rocm-smi)

## Links:
- Docs for installing `rocm` for AMD
  - https://rocm.docs.amd.com/projects/install-on-linux/en/latest/install/quick-start.html
