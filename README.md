# Linux HWINFO64

Written in Python    
This is a scaled down proof of concept. It's a simple script to output a system's hardware information and some simple metrics for the CPU and GPU
In the future, I might expand this to include more of the features of hwinfo64, but it's a simple MVP for now    

## Requirements
- `nvidia-smi` for Nvidia GPUs
- `rocm-smi` for AMD GPUs

## GPU Detection
It first checks for NVIDIA GPUs using nvidia-smi        
Then it checks for AMD GPUs by:            
- Looking at vendor ID in `/sys/class/drm/card0/device/vendor`         
- Using `lspci` to search for AMD graphics adapters       
- The most accurate way to get usage is using rocm-smi, otherwise it relies on `/sys/class/drm/card0/device/gpu_busy_percent`[1]


## Usage Notes:

### CLI Arguments
- `--graph` or `-g`: Run the monitor in graph mode
- `--record` or `-r`: Record metrics to a CSV file for later analysis
- `--output` or `-o`: Specify the output CSV file name (default: hw_metrics.csv)

### Graph Mode
A new display mode that shows line graphs of your hardware metrics over the last 2 minutes
- CPU usage history
- Memory usage history
- GPU utilization history (if available)
- GPU memory usage history (if available)

![Screenshot of tool running in graph mode](assets/graph-view.png)

## Notes
For AMD GPUs, some metrics might not be available depending on your specific card and drivers:
- Temperature reading paths can vary between different AMD cards              
- Memory usage requires ROCm tools to be installed                
- GPU utilization might not be available on older cards/drivers                

![Screenshot of the tool running in the terminal](assets/linux_hw_monitor_screenshot.png)


Additional requirements for AMD GPU support:
- For basic detection: standard Linux utilities like lspci
- For more detailed metrics: AMD's ROCm tools (rocm-smi)

## Links:
- Docs for installing `rocm` for AMD
  - https://rocm.docs.amd.com/projects/install-on-linux/en/latest/install/quick-start.html

[1] I don't know a lot about how linux determines device number, but it will increment the value for `card0` if you ever change your graphics card (presumably it stores the previous device values / configs / whatever). I plan to investigate this further