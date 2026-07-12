import wfdb

def load_physionet_data(record_name='a01', num_samples=5000):
    '''
    هذه الدالة تقوم بالاتصال بقاعدة بيانات PhysioNet 
    وتحميل جزء من إشارة تخطيط القلب (ECG) لاختبار النظام.
    '''
    print(f"جاري جلب البيانات للمريض {record_name} من قاعدة Apnea-ECG...")
    
    # تحميل البيانات مباشرة من السيرفر
    # sampto: تحدد عدد العينات التي نريد سحبها (5000 عينة تعادل 50 ثانية من القراءة)
    record = wfdb.rdrecord(record_name, pn_dir='apnea-ecg', sampto=num_samples)
    
    # استخراج إشارة الفولتية الخاصة بـ ECG وتحويلها لمصفوفة أحادية الأبعاد
    ecg_signal = record.p_signal[:, 0]
    
    # استخراج معدل أخذ العينات (Sampling Frequency) - في هذه القاعدة هو 100 هرتز
    fs = record.fs 
    
    print(f"تم بنجاح تحميل {len(ecg_signal)} نقطة قراءة.")
    print(f"معدل التحديث (Sampling Frequency): {fs} قراءة في الثانية.")
    
    return ecg_signal, fs

