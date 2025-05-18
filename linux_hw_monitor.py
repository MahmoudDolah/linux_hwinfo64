import psutil
import time
import platform
import subprocess
import os
import curses
import glob
import re
import logging
import argparse
import collections
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="hw_monitor.log",
    filemode="a",
)


class SystemMonitor:
    def __init__(self):
        self.gpu_type = self._detect_gpu_type()

    def _detect_gpu_type(self):
        """Detect GPU type (NVIDIA, AMD, or None)"""
        # Check for NVIDIA GPU
        try:
            subprocess.check_output(["nvidia-smi"])
            return "nvidia"
        except (subprocess.SubprocessError, FileNotFoundError):
            logging.debug("NVIDIA GPU not detected via nvidia-smi")

        # Check for AMD GPU
        try:
            # Check if any AMD GPU device exists
            amd_path = "/sys/class/drm/card0/device/vendor"
            if os.path.exists(amd_path):
                with open(amd_path, "r") as f:
                    vendor_id = f.read().strip()
                    # AMD vendor ID is 0x1002
                    if vendor_id == "0x1002":
                        return "amd"

            # Alternative check using lspci
            lspci_output = subprocess.check_output(["lspci"], universal_newlines=True)
            if "amd" in lspci_output.lower() and (
                "vga" in lspci_output.lower() or "display" in lspci_output.lower()
            ):
                return "amd"
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logging.debug(f"Error detecting AMD GPU: {e}")
        except IOError as e:
            logging.debug(f"IO error while detecting AMD GPU: {e}")

        logging.info("No supported GPU detected")
        return "none"

    def get_cpu_info(self):
        """Get CPU information"""
        cpu_info = {
            "usage_percent": psutil.cpu_percent(interval=0.1, percpu=True),
            "average_usage": psutil.cpu_percent(interval=0.1),
            "freq": psutil.cpu_freq(),
            "count": psutil.cpu_count(logical=True),
            "physical_count": psutil.cpu_count(logical=False),
            "temps": self._get_cpu_temps(),
            "name": self._get_cpu_name(),
        }
        return cpu_info

    def _get_cpu_name(self):
        """Get CPU model name"""
        if platform.system() == "Linux":
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("model name"):
                            return line.split(":", 1)[1].strip()
            except IOError as e:
                logging.warning(f"Could not read /proc/cpuinfo: {e}")
        return platform.processor()

    def _get_cpu_temps(self):
        """Get CPU temperatures if available"""
        temps = {}
        if hasattr(psutil, "sensors_temperatures"):
            temp_data = psutil.sensors_temperatures()
            # Look for common CPU temperature sensors
            for chip, sensors in temp_data.items():
                if any(
                    x in chip.lower() for x in ["cpu", "coretemp", "k10temp", "ryzen"]
                ):
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
            nvidia_smi = (
                subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw",
                        "--format=csv,noheader,nounits",
                    ]
                )
                .decode("utf-8")
                .strip()
            )

            name, temp, gpu_util, mem_util, mem_used, mem_total, power = (
                nvidia_smi.split(",")
            )

            gpu_info = {
                "type": "NVIDIA",
                "name": name.strip(),
                "temperature": float(temp.strip()),
                "gpu_utilization": float(gpu_util.strip()),
                "memory_utilization": float(mem_util.strip()),
                "memory_used": float(mem_used.strip()),
                "memory_total": float(mem_total.strip()),
                "power_draw": float(power.strip()) if power.strip() else 0,
            }

            return gpu_info
        except Exception as e:
            return {"status": f"Error fetching NVIDIA GPU info: {str(e)}"}

    def _get_amd_gpu_info(self):
        """Get AMD GPU information"""
        try:
            gpu_info = {"type": "AMD"}

            # Try to get GPU name
            try:
                lspci_output = subprocess.check_output(
                    "lspci | grep -E 'VGA|Display|3D' | grep -i amd",
                    shell=True,
                    universal_newlines=True,
                )
                if lspci_output:
                    # Extract the GPU name from lspci output
                    name_match = lspci_output.split(":")[-1].strip()
                    gpu_info["name"] = name_match
                else:
                    gpu_info["name"] = "AMD GPU"
            except subprocess.SubprocessError as e:
                logging.warning(f"Failed to get AMD GPU name via lspci: {e}")
                gpu_info["name"] = "AMD GPU"

            # Try to read temperature
            try:
                # Different AMD cards might use different paths
                temp_paths = [
                    "/sys/class/drm/card0/device/hwmon/hwmon*/temp1_input",
                    "/sys/class/hwmon/hwmon*/temp1_input",
                ]

                temp_value = None
                for path_pattern in temp_paths:
                    matching_paths = glob.glob(path_pattern)
                    if matching_paths:
                        with open(matching_paths[0], "r") as f:
                            temp_value = (
                                int(f.read().strip()) / 1000
                            )  # Convert from millidegrees to degrees
                            break

                if temp_value is not None:
                    gpu_info["temperature"] = temp_value
                else:
                    logging.debug("No temperature file found for AMD GPU")
            except (IOError, ValueError) as e:
                logging.warning(f"Failed to read AMD GPU temperature: {e}")

            # Try to read GPU utilization
            try:
                gpu_busy_path = "/sys/class/drm/card0/device/gpu_busy_percent"
                if os.path.exists(gpu_busy_path):
                    with open(gpu_busy_path, "r") as f:
                        gpu_info["gpu_utilization"] = float(f.read().strip())
                else:
                    logging.debug("GPU utilization file not found for AMD GPU")
            except (IOError, ValueError) as e:
                logging.warning(f"Failed to read AMD GPU utilization: {e}")

            # Try to get memory info using rocm-smi if available
            try:
                rocm_output = subprocess.check_output(
                    ["rocm-smi", "--showmemuse"], universal_newlines=True
                )
                memory_used_match = re.search(
                    r"GPU Memory Used\s*:\s*(\d+)\s*MB", rocm_output
                )
                memory_total_match = re.search(
                    r"GPU Memory Total\s*:\s*(\d+)\s*MB", rocm_output
                )

                if memory_used_match and memory_total_match:
                    gpu_info["memory_used"] = float(memory_used_match.group(1))
                    gpu_info["memory_total"] = float(memory_total_match.group(1))
                    gpu_info["memory_utilization"] = (
                        gpu_info["memory_used"] / gpu_info["memory_total"]
                    ) * 100
                else:
                    logging.debug("Memory information not found in rocm-smi output")
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                logging.debug(f"rocm-smi not available or failed: {e}")

            # If we couldn't get any dynamic data, at least return the static info
            if len(gpu_info) <= 2:  # Only type and name
                gpu_info["status"] = "Limited AMD GPU info available"
                logging.warning("Limited AMD GPU information available")

            return gpu_info
        except Exception as e:
            logging.error(f"Error fetching AMD GPU info: {e}")
            return {"status": f"Error fetching AMD GPU info: {str(e)}"}

    def get_memory_info(self):
        """Get system memory information"""
        memory = psutil.virtual_memory()
        return {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent,
            "used": memory.used,
            "free": memory.free,
        }


def draw_graph(
    stdscr, y_start, x_start, width, height, data, title, color_pair, y_max=100
):
    """Draw a line graph on the screen

    Args:
        stdscr: Curses window object
        y_start, x_start: Starting coordinates for the graph
        width, height: Dimensions of the graph
        data: List of data points to plot
        title: Graph title
        color_pair: Curses color pair for the graph line
        y_max: Maximum value for y-axis (default: 100%)
    """
    # Draw title
    stdscr.addstr(y_start, x_start, title, curses.A_BOLD)

    # Draw border
    for i in range(height):
        stdscr.addstr(y_start + 1 + i, x_start, "|")
        stdscr.addstr(y_start + 1 + i, x_start + width + 1, "|")

    for i in range(width + 2):
        stdscr.addstr(y_start + height + 1, x_start + i, "-")

    # Draw y-axis labels
    stdscr.addstr(y_start + 1, x_start - 4, f"{y_max:3d}%")
    stdscr.addstr(y_start + height // 2, x_start - 4, f"{y_max // 2:3d}%")
    stdscr.addstr(y_start + height, x_start - 4, "  0%")

    # Plot data points
    data_len = len(data)
    for i in range(min(width, data_len - 1)):
        x1 = i
        y1 = height - int((data[data_len - 1 - i] / y_max) * height)
        x2 = i + 1
        y2 = height - int((data[data_len - 2 - i] / y_max) * height)

        # Ensure y values are within range
        y1 = max(0, min(height - 1, y1))
        y2 = max(0, min(height - 1, y2))

        # Draw line segment
        if x1 == x2:
            start_y = min(y1, y2)
            end_y = max(y1, y2)
            for y in range(start_y, end_y + 1):
                stdscr.addstr(y_start + 1 + y, x_start + 1 + x1, "│", color_pair)
        else:
            if y1 < y2:
                char = "╱"
            elif y1 > y2:
                char = "╲"
            else:
                char = "─"
            stdscr.addstr(y_start + 1 + y1, x_start + 1 + x1, char, color_pair)


def display_monitor_graph(stdscr):
    """Display system metrics as graphs over time"""
    monitor = SystemMonitor()

    # Set up colors
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)

    curses.curs_set(0)  # Hide cursor
    stdscr.timeout(1000)  # Set refresh rate to 1 second

    # Store historical data
    history_length = 120  # 2 minutes of data at 1s intervals
    cpu_history = collections.deque([0] * history_length, maxlen=history_length)
    memory_history = collections.deque([0] * history_length, maxlen=history_length)
    gpu_util_history = collections.deque([0] * history_length, maxlen=history_length)
    gpu_memory_history = collections.deque([0] * history_length, maxlen=history_length)

    # Determine terminal size
    max_y, max_x = stdscr.getmaxyx()
    graph_width = min(max_x - 14, 100)  # Max width or 100 chars

    while True:
        # Get system information
        cpu_info = monitor.get_cpu_info()
        gpu_info = monitor.get_gpu_info()
        memory_info = monitor.get_memory_info()

        # Update history
        cpu_history.appendleft(cpu_info["average_usage"])
        memory_history.appendleft(memory_info["percent"])

        if "gpu_utilization" in gpu_info:
            gpu_util_history.appendleft(gpu_info["gpu_utilization"])
        else:
            gpu_util_history.appendleft(0)

        if "memory_utilization" in gpu_info:
            gpu_memory_history.appendleft(gpu_info["memory_utilization"])
        elif "memory_used" in gpu_info and "memory_total" in gpu_info:
            gpu_memory_history.appendleft(
                (gpu_info["memory_used"] / gpu_info["memory_total"]) * 100
            )
        else:
            gpu_memory_history.appendleft(0)

        # Clear screen
        stdscr.clear()

        # Display title and time
        now = datetime.now().strftime("%H:%M:%S")
        stdscr.addstr(
            0,
            0,
            f"Linux Hardware Monitor (Graph Mode) - {now} (Press 'q' to quit)",
            curses.A_BOLD,
        )

        # Display system info
        stdscr.addstr(
            1,
            0,
            f"CPU: {cpu_info['name']} | "
            + f"Cores: {cpu_info['physical_count']} Physical, {cpu_info['count']} Logical",
        )

        if "status" not in gpu_info:
            gpu_name = gpu_info.get("name", "Unknown GPU")
            gpu_temp = (
                f" | Temp: {gpu_info.get('temperature', 0):.1f}°C"
                if "temperature" in gpu_info
                else ""
            )
            stdscr.addstr(2, 0, f"GPU: {gpu_name}{gpu_temp}")
        else:
            stdscr.addstr(2, 0, f"GPU: {gpu_info['status']}")

        # Draw CPU usage graph
        draw_graph(
            stdscr,
            4,
            5,
            graph_width,
            8,
            cpu_history,
            "CPU Usage (%) - Last 2 Minutes",
            curses.color_pair(1),
        )

        # Draw Memory usage graph
        draw_graph(
            stdscr,
            15,
            5,
            graph_width,
            6,
            memory_history,
            "Memory Usage (%) - Last 2 Minutes",
            curses.color_pair(4),
        )

        # Draw GPU graphs if available
        if "status" not in gpu_info:
            gpu_y_start = 24

            # GPU utilization graph
            if "gpu_utilization" in gpu_info:
                draw_graph(
                    stdscr,
                    gpu_y_start,
                    5,
                    graph_width,
                    6,
                    gpu_util_history,
                    "GPU Utilization (%) - Last 2 Minutes",
                    curses.color_pair(5),
                )
                gpu_y_start += 9

            # GPU memory graph
            if "memory_used" in gpu_info and "memory_total" in gpu_info:
                draw_graph(
                    stdscr,
                    gpu_y_start,
                    5,
                    graph_width,
                    6,
                    gpu_memory_history,
                    "GPU Memory Usage (%) - Last 2 Minutes",
                    curses.color_pair(6),
                )

        # Refresh screen
        stdscr.refresh()

        # Check for key press
        key = stdscr.getch()
        if key == ord("q"):
            break


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
        stdscr.addstr(
            0, 0, f"Linux Hardware Monitor - {now} (Press 'q' to quit)", curses.A_BOLD
        )

        # Get system information
        cpu_info = monitor.get_cpu_info()
        gpu_info = monitor.get_gpu_info()
        memory_info = monitor.get_memory_info()

        # Display CPU information
        stdscr.addstr(2, 0, "CPU INFORMATION", curses.A_BOLD)
        stdscr.addstr(3, 0, f"Model: {cpu_info['name']}")
        stdscr.addstr(
            4,
            0,
            f"Cores: {cpu_info['physical_count']} Physical, {cpu_info['count']} Logical",
        )

        if cpu_info["freq"]:
            current_freq = cpu_info["freq"].current
            max_freq = cpu_info["freq"].max if cpu_info["freq"].max else current_freq
            stdscr.addstr(
                5, 0, f"Frequency: {current_freq:.2f} MHz / {max_freq:.2f} MHz"
            )

        # Display CPU usage per core
        stdscr.addstr(7, 0, "CPU Usage per Core:")
        for i, usage in enumerate(cpu_info["usage_percent"]):
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
        y_pos = 8 + len(cpu_info["usage_percent"]) + 1
        stdscr.addstr(y_pos, 0, "CPU Temperatures:")
        temp_y = y_pos + 1

        if cpu_info["temps"]:
            for sensor, temp in cpu_info["temps"].items():
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

        if "status" in gpu_info:
            stdscr.addstr(gpu_y, 0, gpu_info["status"])
            gpu_y += 1
        else:
            gpu_type = gpu_info.get("type", "Unknown")
            stdscr.addstr(gpu_y, 0, f"Type: {gpu_type}")
            gpu_y += 1

            stdscr.addstr(gpu_y, 0, f"Model: {gpu_info['name']}")
            gpu_y += 1

            # Temperature if available
            if "temperature" in gpu_info:
                temp = gpu_info["temperature"]
                if temp < 60:
                    color = curses.color_pair(1)  # Green
                elif temp < 80:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red
                stdscr.addstr(gpu_y, 0, "Temperature: ", curses.A_BOLD)
                stdscr.addstr(gpu_y, 13, f"{temp:.1f}°C", color)
                gpu_y += 1

            # GPU Utilization if available
            if "gpu_utilization" in gpu_info:
                util = gpu_info["gpu_utilization"]
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
            if "memory_used" in gpu_info and "memory_total" in gpu_info:
                mem_used = gpu_info["memory_used"]
                mem_total = gpu_info["memory_total"]
                mem_percent = (mem_used / mem_total) * 100 if mem_total > 0 else 0
                bar_length = int(mem_percent / 2)

                if mem_percent < 60:
                    color = curses.color_pair(1)  # Green
                elif mem_percent < 85:
                    color = curses.color_pair(2)  # Yellow
                else:
                    color = curses.color_pair(3)  # Red

                stdscr.addstr(
                    gpu_y,
                    0,
                    f"VRAM: {mem_used:.0f}MB / {mem_total:.0f}MB [{mem_percent:5.1f}%] [",
                )
                stdscr.addstr(gpu_y, 38, "#" * bar_length, color)
                stdscr.addstr(gpu_y, 38 + bar_length, " " * (50 - bar_length))
                stdscr.addstr(gpu_y, 88, "]")
                gpu_y += 1

            # Power draw if available
            if "power_draw" in gpu_info and gpu_info["power_draw"] > 0:
                stdscr.addstr(gpu_y, 0, f"Power Draw: {gpu_info['power_draw']:.2f}W")
                gpu_y += 1

        # Display system memory
        mem_y = gpu_y + 1
        stdscr.addstr(mem_y, 0, "SYSTEM MEMORY", curses.A_BOLD)
        mem_y += 1

        mem_used = memory_info["used"] / (1024**3)  # Convert to GB
        mem_total = memory_info["total"] / (1024**3)  # Convert to GB
        mem_percent = memory_info["percent"]
        bar_length = int(mem_percent / 2)

        if mem_percent < 60:
            color = curses.color_pair(1)  # Green
        elif mem_percent < 85:
            color = curses.color_pair(2)  # Yellow
        else:
            color = curses.color_pair(3)  # Red

        stdscr.addstr(
            mem_y,
            0,
            f"RAM: {mem_used:.1f}GB / {mem_total:.1f}GB [{mem_percent:5.1f}%] [",
        )
        stdscr.addstr(mem_y, 36, "#" * bar_length, color)
        stdscr.addstr(mem_y, 36 + bar_length, " " * (50 - bar_length))
        stdscr.addstr(mem_y, 86, "]")

        # Refresh the screen
        stdscr.refresh()

        # Check for quit
        key = stdscr.getch()
        if key == ord("q"):
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Linux Hardware Monitor")
    parser.add_argument(
        "--graph", "-g", action="store_true", help="Show graphical display mode"
    )
    parser.add_argument(
        "--record",
        "-r",
        action="store_true",
        help="Record metrics to a CSV file for later analysis",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="hw_metrics.csv",
        help="Output CSV file when using --record",
    )
    args = parser.parse_args()

    try:
        if args.record:
            # Setup for CSV recording
            import csv

            monitor = SystemMonitor()
            header = [
                "timestamp",
                "cpu_usage",
                "mem_usage",
                "mem_used_gb",
                "mem_total_gb",
            ]

            # Add GPU fields if available
            gpu_info = monitor.get_gpu_info()
            has_gpu = "status" not in gpu_info
            if has_gpu:
                header.extend(["gpu_util", "gpu_mem_util", "gpu_temp"])

            with open(args.output, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(header)

                print(f"Recording metrics to {args.output}... Press Ctrl+C to stop.")

                try:
                    while True:
                        # Get current metrics
                        cpu_info = monitor.get_cpu_info()
                        memory_info = monitor.get_memory_info()
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        # Basic metrics
                        row = [
                            timestamp,
                            cpu_info["average_usage"],
                            memory_info["percent"],
                            memory_info["used"] / (1024**3),  # GB
                            memory_info["total"] / (1024**3),  # GB
                        ]

                        # Add GPU metrics if available
                        if has_gpu:
                            gpu_info = monitor.get_gpu_info()
                            row.extend(
                                [
                                    gpu_info.get("gpu_utilization", 0),
                                    gpu_info.get("memory_utilization", 0),
                                    gpu_info.get("temperature", 0),
                                ]
                            )

                        # Write to CSV
                        writer.writerow(row)
                        f.flush()  # Make sure data is written

                        # Status update
                        print(f"Recorded data point at {timestamp}", end="\r")

                        # Wait before next sample
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\nRecording stopped by user.")
        elif args.graph:
            curses.wrapper(display_monitor_graph)
        else:
            curses.wrapper(display_monitor)
    except KeyboardInterrupt:
        print("Monitor stopped by user.")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        print(f"Error: {e}")
        print("Check hw_monitor.log for details.")
