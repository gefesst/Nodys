"""Polling policy independent of window rendering; explicit service/page bindings."""
class PollingController:
    def __init__(self, services, pages):
        self.services = services  # timer, foreground interval, background interval
        self.pages = pages        # start, stop callbacks in tab order
        self.active_page = None
        self.foreground = None

    def apply(self, foreground, page_index, authenticated, force=False):
        for timer, active_ms, idle_ms in self.services:
            interval = active_ms if foreground else idle_ms
            if authenticated:
                if timer.interval() != interval:
                    timer.setInterval(interval)
                if not timer.isActive():
                    timer.start()
            else:
                timer.stop()
        desired = page_index if foreground and authenticated else None
        if force or desired != self.active_page:
            for index, (start, stop) in enumerate(self.pages):
                if index == desired:
                    start()
                else:
                    stop()
        became_active = foreground and (force or not self.foreground)
        self.active_page, self.foreground = desired, foreground
        return became_active
