import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt
from signals.create_signals import signal

def main():
    fig, (ax1,ax2)=plt.subplots(1,2,figsize=(10,4))
    sin1 = signal.sinusiod(start=-15,end=16,w=np.pi/4,phi=0)
    sin2 = signal.sinusiod(start=-15,end=16,w=np.pi/6,phi=0)

    ax1.stem(np.arange(-15,16),sin1)
    ax1.set_title("W=pi/4")
    ax2.stem(np.arange(-15,16),sin2)
    ax2.set_title("W=pi")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
