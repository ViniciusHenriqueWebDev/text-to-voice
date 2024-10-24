import firebase_admin
from firebase_admin import credentials, storage
import os

# Caminho para o arquivo de chave do serviço
SERVICE_ACCOUNT_KEY_PATH = 'serviceAccountKey.json'

# Inicializar o aplicativo Firebase
def init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
        firebase_admin.initialize_app(cred, {
            'storageBucket': '<SEU_BUCKET>.appspot.com'  # Substitua pelo seu bucket
        })

# Obter referência ao bucket
def get_bucket():
    init_firebase()
    bucket = storage.bucket()
    return bucket
