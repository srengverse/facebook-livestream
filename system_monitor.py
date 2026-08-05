import psutil
import time
import threading

class SystemMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.stats = {
            'cpu_usage': 0,
            'memory_usage': 0,
            'memory_available': 0,
            'disk_usage': 0,
            'network_sent': 0,
            'network_recv': 0,
            'uptime': 0
        }
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()

    def _update_loop(self):
        """Background thread to update stats every 2 seconds without blocking requests."""
        # Initialize CPU tracking
        psutil.cpu_percent(interval=None)
        
        while not self._stop_event.is_set():
            try:
                cpu_usage = psutil.cpu_percent(interval=None)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                net_io = psutil.net_io_counters()
                
                self.stats = {
                    'cpu_usage': cpu_usage,
                    'memory_usage': memory.percent,
                    'memory_available': memory.available / (1024 * 1024),
                    'disk_usage': disk.percent,
                    'network_sent': net_io.bytes_sent,
                    'network_recv': net_io.bytes_recv,
                    'uptime': int(time.time() - self.start_time)
                }
            except Exception:
                pass
            time.sleep(2)

    def get_system_stats(self):
        return self.stats

    def stop(self):
        self._stop_event.set()
