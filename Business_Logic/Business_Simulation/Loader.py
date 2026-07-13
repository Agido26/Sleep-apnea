from Data import data_loader
class Loader():
    def __init__(self,record_name='a01',num_samples=5000):
        self.record_name=record_name
        self.num_samples=num_samples

    def physionet_data(self):
        ecg_signal, fs=data_loader.load_physionet_data(self.record_name,self.num_samples) 
        return ecg_signal,fs
