import numpy as np
import matplotlib.pyplot as plt
class signal:

    def Random(fre_sample):

        t=np.linspace(0,1,fre_sample)
        clean_signal=np.sin(2*np.pi*5*t)
        return clean_signal

    def delta(start,end,pos=0):
        n=np.arange(start,end)
        delta=(n==pos).astype(int)
        return delta
    
    def unit_step(start,end):
        n=np.arange(start,end)
        unit=(n>=0).astype(int)
        return n, unit

    def e_decay(self,start,end,a):
       n, unit = self.unit_step(start,end)
       return unit*(np.abs(a)**n)
    
    def sinusiod(start,end,w,phi=0):
        n=np.arange(start,end)
        x= np.sin(w*n+phi)
        return x

       