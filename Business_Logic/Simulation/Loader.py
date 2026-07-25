from Data import data_loader
import pandas as pd
class DataLoader():
    def __init__(self,record_name,num_samples):
        self.record_name=record_name
        self.num_samples=num_samples

    def __init__(self):
        pass
            
    @staticmethod
    def physionet_data(record_name,num_samples):
        ecg_signal, fs=data_loader.load_physionet_data(record_name,num_samples) 
        return ecg_signal,fs
    @staticmethod
    def load_csv_data(file_path):
        '''
        هذه الدالة تقوم بتحميل البيانات من ملف CSV محلي.
        '''
        try:
            df = pd.read_csv(file_path)
            ecg_signal = df.iloc[:, 0].values  # افترض أن العمود الأول يحتوي على إشارة ECG
            fs = 100  # افترض معدل أخذ العينات (Sampling Frequency) ثابت
            print(f"تم بنجاح تحميل {len(ecg_signal)} نقطة قراءة من ملف CSV.")
            return ecg_signal, fs
        except Exception as e:
            print(f"حدث خطأ أثناء تحميل البيانات من ملف CSV: {e}")
            return None, None
    