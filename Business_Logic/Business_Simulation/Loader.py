from Data import data_loader
import pandas as pd
class Loader():
    def __init__(self,record_name='a01',num_samples=5000):
        self.record_name=record_name
        self.num_samples=num_samples

    def physionet_data(self):
        ecg_signal, fs=data_loader.load_physionet_data(self.record_name,self.num_samples) 
        return ecg_signal,fs
    
    def load_csv_data(self, file_path):
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
    def load_data(self, source='physionet', file_path=None):
        '''
        هذه الدالة تقوم بتحميل البيانات إما من قاعدة بيانات PhysioNet أو من ملف CSV محلي.
        '''
        if source == 'physionet':
            return self.physionet_data()
        elif source == 'csv' and file_path is not None:
            return self.load_csv_data(file_path)
        else:
            print("مصدر البيانات غير صالح. يرجى اختيار 'physionet' أو 'csv' مع تحديد مسار الملف.")
            return None, None