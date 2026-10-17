import sys
sys.path.insert(0, 'src')
from screen import list_x_windows
wins = list_x_windows(':99')
print('count', len(wins))
for w in wins[:12]:
    print(w)
