import progressbar
import time

widgets = [
    'Downloading: ',
    progressbar.Percentage(),
    ' ',
    progressbar.Bar(),
    ' ',
    progressbar.ETA(),
    ' ',
    progressbar.FileTransferSpeed(),
]

bar = progressbar.ProgressBar(widgets=widgets, max_value=1000)
for i in range(1000):
    time.sleep(0.001)
    bar.update(i + 1)
    