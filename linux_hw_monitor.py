import psutil
import time
import platform
import subprocess
import os
import curses
import glob
import re
from datetime import datetime

class SystemMonitor:
    def __init__(self):
        self.gpu_type = self._detect_gpu_type()
        
    def _detect_gpu_type(self):
        """Detect GPU type (NVIDIA, AMD, or None)"""
        # Check for NVIDIA GPU
        try:
            subprocess.check_output(['nvidia-smi'])
            return "nvidia"
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        
        # Check for AMD GPU
        try:
            # Check if any AMD GPU device exists
            amd_path = "/sys/class/drm/card0/device/vendor"
            if os.path.exists(amd_path):
                with open(amd_path, 'r') as f:
                    vendor_id = f.read().strip()
                    # AMD vendor ID is 0x1002
                    if vendor_id == "0x1002":
                        return "amd"
            
            # Alternative check using lspci
            lspci_output = subprocess.check_output(['lspci'], universal_newlines=True)
            if 'amd' in lspci_output.lower() and ('vga' in lspci_output.lower() or 'display' in lspci_output.lower()):
                return "amd"
        except (subprocess.SubprocessError, FileNotFoundError, IOError):
            pass
            
        return "none"
            
    def get_cpu_info(self):
        """Get CPU information"""
        cpu_info = {
            'usage_percent': psutil.cpu_percent(interval=0.1, percpu=True),
            'average_usage': psutil.cpu_percent(interval=0.1),
            'freq': psutil.cpu_freq(),
            'count': psutil.cpu_count(logical=True),
            'physical_count': psutil.cpu_count(logical=False),
            'temps': self._get_cpu_temps(),
            'name': self._get_cpu_name()
        }
        return cpu_info
        
    def _get_cpu_name(self):
        """Get CPU model name"""
        if platform.system() == "Linux":
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if line.startswith('model name'):
                            return line.split(':', 1)[1].strip()
            except:
                pass
        return platform.processor()
    
    def _get_cpu_temps(self):
        """Get CPU temperatures if available"""
        temps = {}
        if hasattr(psutil, "sensors_temperatures"):
            temp_data = psutil.sensors_temperatures()
            # Look for common CPU temperature sensors
            for chip, sensors in temp_data.items():
                if any(x in chip.lower() for x in ['cpu', 'coretemp', 'k10temp', 'ryzen']):
                    for sensor in sensors:
                        temps[sensor.label or chip] = sensor.current
        return temps
        
    def get_gpu_info(self):
        """Get GPU information"""
        if self.gpu_type == "nvidia":
            return self._get_nvidia_gpu_info()
        elif self.gpu_type == "amd":
            return self._get_amd_gpu_info()
        else:
            return {"status": "No supported GPU detected"}
    
    def _get_nvidia_gpu_info(self):
        """Get NVIDIA GPU information"""
        try:
            gpu_info = {}
            nvidia_smi = subprocess.check_output(['nvidia-smi', '--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw', '--format=csv,noheader,nounits']).decode('utf-8').strip()
            
            name, temp, gpu_util, mem_util, mem_used, mem_total, power = nvidia_smi.split(',')
            
            gpu_info = {
                'type': 'NVIDIA',
                'name': name.strip(),
                'temperature': float(temp.strip()),
                'gpu_utilization': float(gpu_util.strip()),
                'memory_utilization': float(mem_util.strip()),
                'memory_used': float(mem_used.strip()),
                'memory_total': float(mem_total.strip()),
                'power_draw': float(power.strip()) if power.strip() else 0
            }
            
            return gpu_info
        except Exception as e:
            return {"status": f"Error fetching NVIDIA GPU info: {str(e)}"}
            
    def _get_amd_gpu_info(self):
        """Get AMD GPU information"""
        try:
            gpu_info = {'type': 'AMD'}
            
            # Try to get GPU name
            try:
                lspci_output = subprocess.check_output(
                    "lspci | grep -E 'VGA|Display|3D' | grep -i amd", 
                    shell=True, 
                    universal_newlines=True
                )
                if lspci_output:
                    # Extract the GPU name from lspci output
                    name_match = lspci_output.split(':')[-1].strip()
                    gpu_info['name'] = name_match
                else:
                    gpu_info['name'] = "AMD GPU"
            except:
                gpu_info['name'] = "AMD GPU"
            
            # Try to read temperature
            try:
                # Different AMD cards might use different paths
                temp_paths = [
                    "/sys/class/drm/card0/device/hwmon/hwmon*/temp1_input",
                    "/sys/class/hwmon/hwmon*/temp1_input"
                ]
                
                temp_value = None
                for path_pattern in temp_paths:
                    matching_paths = glob.glob(path_pattern)
                    if matching_paths:
                        with open(matching_paths[0], 'r') as f:
                            temp_value = int(f.read().strip()) / 1000  # Convert from millidegrees to degrees
                            break
                
                if temp_value is not None:
                    gpu_info['temperature'] = temp_value
            except:
                pass  # Temperature not available
            
            # Try to read GPU utilization
            try:
                gpu_busy_path = "/sys/class/drm/card0/device/gpu_busy_percent"
                if os.path.exists(gpu_busy_path):
                    with open(gpu_busy_path, 'r') as f:
                        gpu_info['gpu_utilization'] = float(f.read().strip())
            except:
                pass  # GPU utilization not available
            
            # Try to get memory info using rocm-smi if available
            try:
                rocm_output = subprocess.check_output(['rocm-smi', '--showmemuse'], universal_newlines=True)
                memory_used_match = re.search(r'GPU Memory Used\s*:\s*(\d+)\s*MB', rocm_output)
                memory_total_match = re.search(r'GPU Memory Total\s*:\s*(\d+)\s*MB', rocm_output)
                
                if memory_used_match and memory_total_match:
                    gpu_info['memory_used'] = float(memory_used_match.group(1))
                    gpu_info['memory_total'] = float(memory_total_match.group(1))
                    gpu_info['memory_utilization'] = (gpu_info['memory_used'] / gpu_info['memory_total']) * 100
            except:
                pass  # rocm-smi not available or failed
                
            # If we couldn't get any dynamic data, at least return the static info
            if len(gpu_info) <= 2:  # Only type and name
                gpu_info["status"] = "Limited AMD GPU info available"
                
            return gpu_info
        except Exception as e:
            return {"status": f"Error fetching AMD GPU info: {str(e)}"}
    
    def get_memory_info(self):
        """Get system memory information"""
        memory = psutil.virtual_memory()
        return {
            'total': memory.total,
            'available': memory.available,
            'percent': memory.percent,
            'used': memory.used,
            'free': memory.free
        }

def display_monitor(stdscr):
    monitor = SystemMonitor()
    
    # Set up colors
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    
    curses.curs_set(0)  # Hide cursor
    stdscr.timeout(1000)  # Set getch() timeout to 1 second
    
    while True:
        stdscr.clear()
        
        # Display time
        now = datetime.now().strftime("%H:%M:%S")
        stdscr.addstr(0, 0, f"Linux Hardware Monitor - {now} (Press 'q' to quit)", curses.A_BOLD)
        
        # Get system information
        cpu_info = monitor.get_cpu_info()
        gpu_info = monitor.get_gpu_info()
        memory_info = monitor.get_memory_info()
        
        # Display CPU information
        stdscr.addstr(2, 0, "CPU INFORMATION", curses.A_BOLD)
        stdscr.addstr(3, 0, f"Model: {cpu_info['name']}")
        stdscr.addstr(4, 0, f"Cores: {cpu_info['physical_count']} Physical, {cpu_info['count']} Logical")
        
        if cpu_info['freq']:
            current_freq = cpu_info['freq'].current
            max_freq = cpu_info['freq'].max if cpu_info['freq'].max else current_freq
            stdscr.addstr(5, 0, f"Frequency: {current_freq:.2f} MHz / {max_freq:.2f} MHz")
        
        # Display CPU usage per core
        stdscr.addstr(7, 0, "CPU Usage per Core:")
        for i, usage in enumerate(cpu_info['usage_percent']):
            y_pos = 8 + i
            bar_length = int(usage / 2)  # Scale to fit terminal
            
            # Color based on usage
            if usage < 60:
                color = curses.color_pair(1)  # Green
            elif usage < 85:
                color = curses.color_pair(2)  # Yellow
            else:
                color = curses.color_pair(3)  # Red
                
            stdscr.addstr(y_pos, 0, f"Core {i}: {usage:5.1f}% [")
            stdscr.addstr(y_pos, 15, "#" * bar_length, color)
            stdscr.addstr(y_pos, 15 + bar_length, " " * (50 - bar_length))
            stdscr.addstr(y_pos, 65, "]")
            
        # Display CPU temperature
        y_pos = 8 + len(cpu_info['usage_percent']) + 1
        stdscr.addstr(y_pos, 0, "CPU Temperatures:")
        temp_y = y_pos + 1
        
        if cpu_info['temps']:
            for sensor, temp in cpu_info['temps'].items():
                if temp < 60:
                    color = curses.color_pair(1)  # Green
                elif temp < 80:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red
                stdscr.addstr(temp_y, 0, f"{sensor}: ", curses.A_BOLD)
                stdscr.addstr(temp_y, 20, f"{temp:.1f}°C", color)
                temp_y += 1
        else:
            stdscr.addstr(temp_y, 0, "Temperature data not available")
            temp_y += 1
            
        # Display GPU information
        gpu_y = temp_y + 1
        stdscr.addstr(gpu_y, 0, "GPU INFORMATION", curses.A_BOLD)
        gpu_y += 1
        
        if 'status' in gpu_info:
            stdscr.addstr(gpu_y, 0, gpu_info['status'])
            gpu_y += 1
        else:
            gpu_type = gpu_info.get('type', 'Unknown')
            stdscr.addstr(gpu_y, 0, f"Type: {gpu_type}")
            gpu_y += 1
            
            stdscr.addstr(gpu_y, 0, f"Model: {gpu_info['name']}")
            gpu_y += 1
            
            # Temperature if available
            if 'temperature' in gpu_info:
                temp = gpu_info['temperature']
                if temp < 60:
                    color = curses.color_pair(1)  # Green
                elif temp < 80:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red
                stdscr.addstr(gpu_y, 0, f"Temperature: ", curses.A_BOLD)
                stdscr.addstr(gpu_y, 13, f"{temp:.1f}°C", color)
                gpu_y += 1
            
            # GPU Utilization if available
            if 'gpu_utilization' in gpu_info:
                util = gpu_info['gpu_utilization']
                bar_length = int(util / 2)
                if util < 60:
                    color = curses.color_pair(1)  # Green
                elif util < 85:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red
                stdscr.addstr(gpu_y, 0, f"GPU Usage: {util:5.1f}% [")
                stdscr.addstr(gpu_y, 16, "#" * bar_length, color)
                stdscr.addstr(gpu_y, 16 + bar_length, " " * (50 - bar_length))
                stdscr.addstr(gpu_y, 66, "]")
                gpu_y += 1
            
            # Memory if available
            if 'memory_used' in gpu_info and 'memory_total' in gpu_info:
                mem_used = gpu_info['memory_used']
                mem_total = gpu_info['memory_total']
                mem_percent = (mem_used / mem_total) * 100 if mem_total > 0 else 0
                bar_length = int(mem_percent / 2)
                
                if mem_percent < 60:
                    color = curses.color_pair(1)  # Green
                elif mem_percent < 85:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red
                    
                stdscr.addstr(gpu_y, 0, f"VRAM: {mem_used:.0f}MB / {mem_total:.0f}MB [{mem_percent:5.1f}%] [")
                stdscr.addstr(gpu_y, 38, "#" * bar_length, color)
                stdscr.addstr(gpu_y, 38 + bar_length, " " * (50 - bar_length))
                stdscr.addstr(gpu_y, 88, "]")
                gpu_y += 1
            
            # Power draw if available
            if 'power_draw' in gpu_info and gpu_info['power_draw'] > 0:
                stdscr.addstr(gpu_y, 0, f"Power Draw: {gpu_info['power_draw']:.2f}W")
                gpu_y += 1
        
        # Display system memory
        mem_y = gpu_y + 1
        stdscr.addstr(mem_y, 0, "SYSTEM MEMORY", curses.A_BOLD)
        mem_y += 1
        
        mem_used = memory_info['used'] / (1024**3)  # Convert to GB
        mem_total = memory_info['total'] / (1024**3)  # Convert to GB
        mem_percent = memory_info['percent']
        bar_length = int(mem_percent / 2)
        
        if mem_percent < 60:
            color = curses.color_pair(1)  # Green
        elif mem_percent < 85:
            color = curses.color_pair(2)  # Yellow
        else:
            color = curses.color_pair(3)  # Red
            
        stdscr.addstr(mem_y, 0, f"RAM: {mem_used:.1f}GB / {mem_total:.1f}GB [{mem_percent:5.1f}%] [")
        stdscr.addstr(mem_y, 36, "#" * bar_length, color)
        stdscr.addstr(mem_y, 36 + bar_length, " " * (50 - bar_length))
        stdscr.addstr(mem_y, 86, "]")
        
        # Refresh the screen
        stdscr.refresh()
        
        # Check for quit
        key = stdscr.getch()
        if key == ord('q'):
            break

if __name__ == "__main__":
    try:
        curses.wrapper(display_monitor)
    except KeyboardInterrupt:
        print("Monitor stopped.")
