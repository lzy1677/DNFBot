import time, sys
sys.path.insert(0, ".")
from action.input_driver import InputDriver

time.sleep(3)  # 3 秒内切到游戏
d = InputDriver()
d.press("x", 0.1)
d.press("x", 0.1)
d.press("x", 0.1)
d.press("x", 0.1)
d.press("x", 0.1)
d.press("x", 0.1)
d.press("x", 0.1)
print("done")