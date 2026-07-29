import numpy as np
from scipy.signal import find_peaks

class ECGProcessor:
    @staticmethod
    def calculate_peaks_and_bpm(y_data, fs, height_threshold=0.5, min_distance=40):
        # 1. إيجاد القمم (R-Peaks)
        peaks, _ = find_peaks(y_data, height=height_threshold, distance=min_distance)
        
        bpm = 0
        if len(peaks) >= 2:
            # 2. إيجاد المسافة بالنقاط بين *كل* قمتين متتاليتين في الشاشة
            # دالة diff تطرح كل رقم في المصفوفة من الرقم الذي يسبقه مباشرة
            peak_intervals = np.diff(peaks) 
            
            # 3. حساب متوسط المسافات (للتخلص من تأثير أي قمة وهمية)
            average_interval_samples = np.mean(peak_intervals)
            
            # 4. تحويل المتوسط إلى ثواني
            time_between_beats = average_interval_samples / fs
            
            # 5. حساب النبض في الدقيقة
            if time_between_beats > 0:
                bpm = 60 / time_between_beats
                
        return peaks, bpm