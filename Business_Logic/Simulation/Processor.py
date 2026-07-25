from scipy.signal import find_peaks

class ECGProcessor:
    @staticmethod
    def calculate_peaks_and_bpm(y_data, fs, height_threshold=0.5, min_distance=40):
        """
        دالة تستقبل إشارة الـ ECG الحالية وتقوم بإرجاع أماكن القمم ومعدل نبضات القلب
        """
        # 1. إيجاد القمم (R-Peaks)
        peaks, _ = find_peaks(y_data, height=height_threshold, distance=min_distance)
        
        bpm = 0
        # 2. حساب الـ BPM إذا كان لدينا قمتين على الأقل في النافذة الحالية
        if len(peaks) >= 2:
            last_peak = peaks[-1]
            previous_peak = peaks[-2]
            
            # المسافة الزمنية بين آخر نبضتين
            samples_between_peaks = last_peak - previous_peak
            time_between_beats = samples_between_peaks / fs
            
            if time_between_beats > 0:
                bpm = 60 / time_between_beats
                
        return peaks, bpm