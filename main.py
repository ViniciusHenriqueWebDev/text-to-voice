import os
import requests
import tkinter as tk
from tkinter import messagebox, simpledialog
from tkinter import ttk
from ttkthemes import ThemedTk  # type: ignore
from PIL import Image, ImageTk  # For handling icons (optional)
import re
import threading  # To prevent UI blocking during uploads
import firebase_admin
from firebase_admin import credentials, storage
from firebase_admin import firestore
import uuid  # For generating UUIDs
from datetime import timedelta
import urllib.parse  # For encoding URLs
from playsound import playsound  # To play audio
import pygame

# Azure OpenAI API configuration
api_key = "x"  # Utilize variáveis de ambiente
endpoint = "x"  # Atualize com o seu endpoint Azure OpenAI
api_version = "2023-05-15"
deployment_name = "gpt-4o-mini"  # Seu nome de deployment

# Configurações do Eleven Labs API
elevenlabs_api_key = "x"  # Utilize variáveis de ambiente
elevenlabs_voice_id = "x"  # Substitua pelo ID da voz correta

# Firebase Storage configuration
SERVICE_ACCOUNT_KEY_PATH = 'serviceAccountKey.json'  # Path to your service account key file
FIREBASE_STORAGE_BUCKET = 'iapresentador.appspot.com'  # Replace with your bucket

# Initialize Firebase Admin SDK
def init_firebase():
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
            firebase_admin.initialize_app(cred, {
                'storageBucket': FIREBASE_STORAGE_BUCKET
            })
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao inicializar o Firebase: {e}")
            return None, None
    bucket = storage.bucket()
    db = firestore.client()
    return bucket, db

# Function to list available voices
def obter_vozes_disponiveis():
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {
        "Accept": "application/json",
        "xi-api-key": elevenlabs_api_key,
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Erro ao obter vozes: {e}")
        messagebox.showerror("Erro", f"Erro ao obter vozes: {e}")
        return

    voices = response.json()
    for voice in voices['voices']:
        language = voice.get('language', 'Unknown')
        print(f"Name: {voice['name']}, ID: {voice['voice_id']}, Language: {language}")

# Function to split text into coherent sentences
def dividir_em_frases_coerentes(texto, min_words=8):
    system_prompt = (
        "Você é um assistente que divide textos em falas coerentes que serão legendadas. "
        "Garanta que cada fala esteja em uma linha separada, com sentido completo e natural, evitando falas com muitas palavras para facilitar a leitura da legenda com base no contexto da nossa apresentação."
    )

    # Prompt for the API
    prompt = (
        f"Divida o seguinte texto em falas, cada uma representando uma ideia completa. "
        f"As falas devem estar em uma linha separada cada, conter no mínimo {min_words} palavras, "
        f"e o texto deve copiar exatamente o que eu mandar: {texto}"
    )

    url = f"{endpoint}/openai/deployments/{deployment_name}/chat/completions?api-version={api_version}"

    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
    }

    data = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Erro ao acessar a API OpenAI: {e}")
        messagebox.showerror("Erro", f"Erro ao acessar a API OpenAI: {e}")
        return []

    response_data = response.json()
    content = response_data['choices'][0]['message']['content']

    # Split sentences based on line breaks
    frases = content.strip().split('\n')

    # Return only non-empty phrases without extra spaces
    frases = [frase.strip() for frase in frases if frase.strip()]

    # Validate and adjust phrases that don't meet the minimum word count
    frases_validadas = []
    for frase in frases:
        word_count = len(frase.split())
        if word_count >= min_words:
            frases_validadas.append(frase)
        else:
            # Append to the last phrase if possible
            if frases_validadas:
                frases_validadas[-1] += ' ' + frase
            else:
                frases_validadas.append(frase)

    # Ensure again the minimum word count after adjustments
    frases_final = []
    for frase in frases_validadas:
        word_count = len(frase.split())
        if word_count >= min_words:
            frases_final.append(frase)
        else:
            # If there are still shorter phrases, append to the previous or keep them
            if frases_final:
                frases_final[-1] += ' ' + frase
            else:
                frases_final.append(frase)

    return frases_final

# Custom Dialog to Edit Phrases with a Larger Text Box
class EditarFraseDialog(tk.Toplevel):
    def __init__(self, parent, frase_atual):
        super().__init__(parent)
        self.title("Editar Frase")
        self.geometry("600x250")  # Increased for better visualization
        self.resizable(False, False)
        self.grab_set()  # Modal

        self.frase_editada = None

        label = tk.Label(self, text="Modifique a frase:", font=('Helvetica', 12))
        label.pack(pady=10)

        self.texto = tk.Text(self, width=70, height=7, font=('Helvetica', 12))
        self.texto.pack(padx=10, pady=5)
        self.texto.insert(tk.END, frase_atual)

        frame_botoes = tk.Frame(self)
        frame_botoes.pack(pady=10)

        botao_ok = tk.Button(frame_botoes, text="OK", width=10, command=self.ok, bg='#4CAF50', fg='white', font=('Helvetica', 10, 'bold'))
        botao_ok.pack(side=tk.LEFT, padx=10)

        botao_cancelar = tk.Button(frame_botoes, text="Cancelar", width=10, command=self.cancelar, bg='#f44336', fg='white', font=('Helvetica', 10, 'bold'))
        botao_cancelar.pack(side=tk.LEFT, padx=10)

    def ok(self):
        texto = self.texto.get("1.0", tk.END).strip()
        if texto:
            self.frase_editada = texto
            self.destroy()
        else:
            messagebox.showwarning("Aviso", "A frase não pode estar vazia.", parent=self)

    def cancelar(self):
        self.destroy()

# Function to generate Signed URL
def gerar_signed_url(blob, expiration=timedelta(hours=1)):
    """
    Generates a signed URL for a blob in Firebase Storage.

    Args:
        blob (google.cloud.storage.blob.Blob): The blob to generate the URL for.
        expiration (timedelta): The expiration time of the URL.

    Returns:
        str: A signed URL.
    """
    try:
        url = blob.generate_signed_url(expiration=expiration)
        return url
    except Exception as e:
        print(f"Erro ao gerar signed URL: {e}")
        return None

# Function to generate audio and subtitle using Eleven Labs API
def gerar_audio_e_legenda(frase, folder_path, base_name, idx):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": elevenlabs_api_key,
    }
    data = {
        "text": frase,
        "voice_settings": {
            "stability": 1,
            "similarity_boost": 0.6,
        },
        "model_id": "eleven_multilingual_v2",
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Erro ao gerar áudio: {e}")
        if response is not None:
            print(f"Conteúdo da resposta: {response.text}")
        messagebox.showerror("Erro", f"Erro ao gerar áudio: {e}")
        return None

    # Create the folder if it doesn't exist
    os.makedirs(folder_path, exist_ok=True)

    base_filename = f"{base_name}-frase-{idx}"
    audio_filename = f"{base_filename}.mp3"
    audio_filepath = os.path.join(folder_path, audio_filename)

    # Save the audio file
    try:
        with open(audio_filepath, "wb") as f:
            f.write(response.content)
    except Exception as e:
        print(f"Erro ao salvar áudio: {e}")
        messagebox.showerror("Erro", f"Erro ao salvar áudio: {e}")
        return None

    # Save the corresponding subtitle file
    legenda_filename = f"{base_filename}.txt"
    legenda_filepath = os.path.join(folder_path, legenda_filename)
    try:
        with open(legenda_filepath, "w", encoding="utf-8") as f:
            f.write(frase)
    except Exception as e:
        print(f"Erro ao salvar legenda: {e}")
        messagebox.showerror("Erro", f"Erro ao salvar legenda: {e}")
        return None

    return audio_filepath

# Function to update Firestore
def atualizar_firestore(db, document_id, audio_url, legenda, parent_window, slide_order):
    """
    Updates the specific document in Firestore by adding the audio URL and subtitle to an existing slide.

    Args:
        db (firestore.Client): Firestore client.
        document_id (str): Document ID in the 'presentations' collection.
        audio_url (str): Audio URL in Firebase Storage.
        legenda (str): Subtitle corresponding to the audio.
        parent_window (tk.Tk or tk.Toplevel): Parent window to display dialog boxes.
        slide_order (int): Order of the slide to add the audio and subtitle to.
    """
    try:
        # Reference to the document
        doc_ref = db.collection('presentations').document(document_id)

        # Retrieve the document
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            slides = data.get('slides', [])

            # Find the slide with the specified order
            slide_found = False
            for slide in slides:
                if slide.get('order') == slide_order:
                    audios = slide.get('audios', [])
                    audios.append({
                        'audioUrl': audio_url,
                        'legenda': legenda
                    })
                    slide['audios'] = audios
                    slide_found = True
                    break

            if not slide_found:
                messagebox.showerror("Erro", f"Slide com ordem {slide_order} não encontrado.", parent=parent_window)
                return

            # Update the document in Firestore
            doc_ref.update({'slides': slides})
        else:
            messagebox.showerror("Erro", f"Documento com ID {document_id} não existe.", parent=parent_window)
    except Exception as e:
        messagebox.showerror("Erro", f"Erro ao atualizar o Firestore: {e}", parent=parent_window)

# Function to process the entered text
def iniciar_processamento(texto, base_name):
    frases = dividir_em_frases_coerentes(texto, min_words=8)
    exibir_frases(frases, base_name)

# Function to display list of phrases in a tkinter window
def exibir_frases(frases, base_name):
    lista_window = tk.Toplevel()
    lista_window.title("Frases Geradas")
    lista_window.geometry("1200x800")  # Increased for better visualization

    # Apply theme
    style = ttk.Style(lista_window)
    style.theme_use('arc')  # You can choose other available themes

    # Style the Treeview
    style.configure("Treeview.Heading", font=('Helvetica', 12, 'bold'))
    style.configure("Treeview", font=('Helvetica', 11), rowheight=25)
    style.map('Treeview', background=[('selected', '#347083')], foreground=[('selected', 'white')])

    # Create 'audios' folder if it doesn't exist
    os.makedirs('audios', exist_ok=True)

    # Get reference to Firebase Storage bucket and Firestore client
    bucket, db = init_firebase()
    if bucket is None or db is None:
        lista_window.destroy()
        return

    # Retrieve Firestore document to get existing slide orders
    document_id = "0QhyptyCMN88m8jRsGl4"  # Ensure this ID is correct
    try:
        doc_ref = db.collection('presentations').document(document_id)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            slides = data.get('slides', [])
            slide_orders = sorted([slide.get('order') for slide in slides if 'order' in slide])
        else:
            messagebox.showerror("Erro", f"Documento com ID {document_id} não existe.", parent=lista_window)
            lista_window.destroy()
            return
    except Exception as e:
        messagebox.showerror("Erro", f"Erro ao recuperar slides do Firestore: {e}", parent=lista_window)
        lista_window.destroy()
        return

    # Function to get the next available base name
    def get_available_base_name_internal(bucket, base_name):
        prefix = f"audios/{base_name}/"
        blobs = list(bucket.list_blobs(prefix=prefix, max_results=1))
        if not blobs:
            return base_name

        # If it exists, find the next available name
        match = re.match(r"^(.*?)-(\d+)$", base_name)
        if match:
            prefix_part, number = match.groups()
            index = int(number) + 1
        else:
            prefix_part = base_name
            index = 1

        while True:
            new_base_name = f"{prefix_part}-{index}"
            new_prefix = f"audios/{new_base_name}/"
            blobs = list(bucket.list_blobs(prefix=new_prefix, max_results=1))
            if not blobs:
                return new_base_name
            index += 1

    # Check and adjust the base name if necessary
    available_base_name = get_available_base_name_internal(bucket, base_name)
    if available_base_name != base_name:
        messagebox.showinfo("Informação", f"A pasta '{base_name}' já existe no Firebase Storage.\nUsando '{available_base_name}' em seu lugar.", parent=lista_window)
        base_name = available_base_name  # Update base_name to the available one

    # Create Treeview with columns 'Número', 'Frase', 'Palavras', 'Status'
    tree = ttk.Treeview(lista_window, columns=('Número', 'Frase', 'Palavras', 'Status'), show='headings', selectmode='browse')
    tree.heading('Número', text='Nº')
    tree.heading('Frase', text='Frase')
    tree.heading('Palavras', text='Palavras')
    tree.heading('Status', text='Status')

    tree.column('Número', width=50, anchor='center')
    tree.column('Frase', width=700, anchor='w')
    tree.column('Palavras', width=80, anchor='center')
    tree.column('Status', width=150, anchor='center')

    # Alternate row colors
    tree.tag_configure('oddrow', background='#f0f0f0')
    tree.tag_configure('evenrow', background='#d9d9d9')

    # Insert phrases into the Treeview with sequential numbering and word count
    for idx, frase in enumerate(frases, 1):
        word_count = len(frase.split())
        tag = 'oddrow' if idx % 2 else 'evenrow'
        tree.insert('', tk.END, values=(idx, frase, word_count, 'Pendente'), tags=(tag,))

    tree.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

    # Add optional progress bar
    progress = ttk.Progressbar(lista_window, orient='horizontal', mode='determinate', length=800)
    progress.pack(pady=10)

    # Add a menu bar
    menu_bar = tk.Menu(lista_window)
    lista_window.config(menu=menu_bar)

    # File Menu
    arquivo_menu = tk.Menu(menu_bar, tearoff=0)
    menu_bar.add_cascade(label="Arquivo", menu=arquivo_menu)
    arquivo_menu.add_command(label="Sair", command=lista_window.destroy)

    # Help Menu
    ajuda_menu = tk.Menu(menu_bar, tearoff=0)
    menu_bar.add_cascade(label="Ajuda", menu=ajuda_menu)
    ajuda_menu.add_command(label="Sobre", command=lambda: messagebox.showinfo("Sobre", "Aplicativo de Geração de Áudio e Legendas"))

    # Frame for action buttons
    frame_botoes = tk.Frame(lista_window)
    frame_botoes.pack(pady=10)

    # Add a Combobox to select slide_order
    frame_slide = tk.Frame(lista_window)
    frame_slide.pack(pady=10, padx=20, fill=tk.X)

    label_slide = tk.Label(frame_slide, text="Selecione o Slide para adicionar os Áudios:", font=('Helvetica', 12))
    label_slide.pack(side=tk.LEFT, padx=5, pady=5)

    selected_slide = tk.StringVar()
    combobox_slide = ttk.Combobox(frame_slide, textvariable=selected_slide, state='readonly')
    combobox_slide['values'] = slide_orders
    if slide_orders:
        combobox_slide.current(0)  # Select the first slide by default
    combobox_slide.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X, expand=True)

    # Function to add a new phrase
    def adicionar_frase():
        nova_frase = simpledialog.askstring("Adicionar Frase", "Digite a nova frase:", parent=lista_window)
        if nova_frase:
            nova_frase = nova_frase.strip()
            if nova_frase:
                num_frases = len(tree.get_children())
                word_count = len(nova_frase.split())
                tag = 'oddrow' if (num_frases + 1) % 2 else 'evenrow'
                tree.insert('', tk.END, values=(num_frases + 1, nova_frase, word_count, 'Pendente'), tags=(tag,))
            else:
                messagebox.showwarning("Aviso", "A frase não pode estar vazia.", parent=lista_window)

    # Function to edit the selected phrase
    def editar_frase():
        selected_item = tree.selection()
        if not selected_item:
            messagebox.showwarning("Aviso", "Por favor, selecione uma frase para editar.", parent=lista_window)
            return
        item_id = selected_item[0]
        frase_atual = tree.item(item_id, 'values')[1]
        dialog = EditarFraseDialog(lista_window, frase_atual)
        lista_window.wait_window(dialog)
        if dialog.frase_editada:
            word_count = len(dialog.frase_editada.split())
            tree.set(item_id, 'Frase', dialog.frase_editada)
            tree.set(item_id, 'Palavras', word_count)

    # Function to delete the selected phrase
    def apagar_frase():
        selected_item = tree.selection()
        if not selected_item:
            messagebox.showwarning("Aviso", "Por favor, selecione uma frase para apagar.", parent=lista_window)
            return
        confirm = messagebox.askyesno("Confirmar", "Tem certeza que deseja apagar a frase selecionada?", parent=lista_window)
        if confirm:
            tree.delete(selected_item)
            # Update phrase numbers and tags
            for idx, item in enumerate(tree.get_children(), 1):
                word_count = tree.item(item, 'values')[2]
                tree.set(item, 'Número', idx)
                tag = 'oddrow' if idx % 2 else 'evenrow'
                tree.item(item, tags=(tag,))

    # Function to move the selected phrase up
    def mover_para_cima():
        selected_item = tree.selection()
        if not selected_item:
            messagebox.showwarning("Aviso", "Por favor, selecione uma frase para mover para cima.", parent=lista_window)
            return
        item_id = selected_item[0]
        index = tree.index(item_id)
        if index == 0:
            messagebox.showinfo("Informação", "A frase selecionada já está no topo.", parent=lista_window)
            return
        acima_item = tree.get_children()[index - 1]
        # Swap phrase values
        valores_acima = tree.item(acima_item, 'values')
        valores_atual = tree.item(item_id, 'values')
        tree.item(acima_item, values=valores_atual)
        tree.item(item_id, values=valores_acima)
        # Update tags for alternating colors and numbers
        for idx, item in enumerate(tree.get_children(), 1):
            tree.set(item, 'Número', idx)
            tag = 'oddrow' if idx % 2 else 'evenrow'
            tree.item(item, tags=(tag,))
        # Select the item that was moved up
        tree.selection_set(acima_item)
        tree.focus(acima_item)

    # Function to move the selected phrase down
    def mover_para_baixo():
        selected_item = tree.selection()
        if not selected_item:
            messagebox.showwarning("Aviso", "Por favor, selecione uma frase para mover para baixo.", parent=lista_window)
            return
        item_id = selected_item[0]
        index = tree.index(item_id)
        if index == len(tree.get_children()) - 1:
            messagebox.showinfo("Informação", "A frase selecionada já está na base.", parent=lista_window)
            return
        abaixo_item = tree.get_children()[index + 1]
        # Swap phrase values
        valores_abaixo = tree.item(abaixo_item, 'values')
        valores_atual = tree.item(item_id, 'values')
        tree.item(abaixo_item, values=valores_atual)
        tree.item(item_id, values=valores_abaixo)
        # Update tags for alternating colors and numbers
        for idx, item in enumerate(tree.get_children(), 1):
            tree.set(item, 'Número', idx)
            tag = 'oddrow' if idx % 2 else 'evenrow'
            tree.item(item, tags=(tag,))
        # Select the item that was moved down
        tree.selection_set(abaixo_item)
        tree.focus(abaixo_item)

    # Function to generate audio and subtitle
    def gerar_audios_e_legendas():
        def task():
            total = len(tree.get_children())
            if total == 0:
                messagebox.showwarning("Aviso", "Não há frases para processar.", parent=lista_window)
                return
            progress['maximum'] = total
            progress['value'] = 0
            for idx, item in enumerate(tree.get_children(), 1):
                frase = tree.item(item, 'values')[1]
                word_count = tree.item(item, 'values')[2]
                # Generate audio and subtitle, save in 'audios' folder
                audio_filepath = gerar_audio_e_legenda(frase, 'audios', base_name, idx)
                if audio_filepath:
                    status = 'Sucesso'
                    # Change status color to green
                    tree.tag_configure('sucesso', foreground='green')
                    values = list(tree.item(item, 'values'))
                    values[3] = status  # Update 'Status'
                    tree.item(item, values=values, tags=('sucesso',))
                else:
                    status = 'Falha'
                    # Change status color to red
                    tree.tag_configure('falha', foreground='red')
                    values = list(tree.item(item, 'values'))
                    values[3] = status  # Update 'Status'
                    tree.item(item, values=values, tags=('falha',))
                # Update progress bar
                progress['value'] = idx
                # Lightly update the interface
                lista_window.update_idletasks()
            messagebox.showinfo("Conclusão", "Áudios e legendas gerados com sucesso.", parent=lista_window)
            # Enable the button to send to Firebase after completion
            botao_enviar.config(state='normal')

        threading.Thread(target=task).start()

    # Function to send files to Firebase Storage with Firestore update
    def enviar_ao_firebase():
        def task():
            # Disable the button during upload
            botao_enviar.config(state='disabled')
            base_folder = f"audios/{base_name}"

            # Specific document ID in the 'presentations' collection
            document_id = "0QhyptyCMN88m8jRsGl4"  # Ensure this ID is correct

            # Get the selected slide order
            try:
                slide_order = int(selected_slide.get())
            except ValueError:
                messagebox.showerror("Erro", "Selecione uma ordem de slide válida.", parent=lista_window)
                botao_enviar.config(state='normal')
                return

            for idx, item in enumerate(tree.get_children(), 1):
                values = tree.item(item, 'values')
                status = values[3]
                if status != 'Sucesso':
                    continue  # Only send files with success status
                filename_base = f"{base_name}-frase-{idx}"
                audio_filename = f"{filename_base}.mp3"
                legenda_filename = f"{filename_base}.txt"

                # Local paths
                audio_local_path = os.path.join('audios', audio_filename)
                legenda_local_path = os.path.join('audios', legenda_filename)

                # Firebase Storage paths
                audio_remote_path = f"{base_folder}/{audio_filename}"
                legenda_remote_path = f"{base_folder}/{legenda_filename}"

                # Blob references
                blob_audio = bucket.blob(audio_remote_path)
                blob_legenda = bucket.blob(legenda_remote_path)

                # Check if the audio already exists
                try:
                    if blob_audio.exists():
                        overwrite_audio = messagebox.askyesno(
                            "Confirmação de Sobrescrita",
                            f"O arquivo '{audio_filename}' já existe no Firebase Storage.\nDeseja sobrescrevê-lo?",
                            parent=lista_window
                        )
                        if not overwrite_audio:
                            print(f"Arquivo '{audio_remote_path}' não foi sobrescrito.")
                            continue  # Skip uploading this file
                except Exception as e:
                    print(f"Erro ao verificar existência do áudio: {e}")
                    messagebox.showerror("Erro", f"Erro ao verificar existência do áudio: {e}", parent=lista_window)
                    continue

                # Upload the audio file
                try:
                    blob_audio.upload_from_filename(audio_local_path, content_type='audio/mpeg')
                    print(f"Arquivo '{audio_remote_path}' enviado com sucesso.")
                except Exception as e:
                    print(f"Erro ao enviar '{audio_remote_path}': {e}")
                    messagebox.showerror("Erro", f"Erro ao enviar '{audio_remote_path}': {e}", parent=lista_window)
                    continue

                # Generate Signed URL for the audio
                audio_url = gerar_signed_url(blob_audio, expiration=timedelta(days=7))  # Adjust time as needed
                if not audio_url:
                    messagebox.showerror("Erro", f"Erro ao gerar URL para '{audio_remote_path}'.", parent=lista_window)
                    continue

                # Upload the subtitle file
                try:
                    blob_legenda.upload_from_filename(legenda_local_path, content_type='text/plain')
                    print(f"Arquivo '{legenda_remote_path}' enviado com sucesso.")
                except Exception as e:
                    print(f"Erro ao enviar '{legenda_remote_path}': {e}")
                    messagebox.showerror("Erro", f"Erro ao enviar '{legenda_remote_path}': {e}", parent=lista_window)
                    continue

                # Generate Signed URL for the subtitle (if necessary)
                legenda_url = gerar_signed_url(blob_legenda, expiration=timedelta(days=7))
                if not legenda_url:
                    messagebox.showerror("Erro", f"Erro ao gerar URL para '{legenda_remote_path}'.", parent=lista_window)
                    continue

                # Get the subtitle from the locally saved file
                try:
                    with open(legenda_local_path, "r", encoding="utf-8") as f:
                        legenda = f.read().strip()
                except Exception as e:
                    print(f"Erro ao ler a legenda: {e}")
                    messagebox.showerror("Erro", f"Erro ao ler a legenda: {e}", parent=lista_window)
                    continue

                # Update Firestore with the audio URL and subtitle
                try:
                    atualizar_firestore(db, document_id, audio_url, legenda, lista_window, slide_order)
                except Exception as e:
                    print(f"Erro ao atualizar o Firestore: {e}")
                    messagebox.showerror("Erro", f"Erro ao atualizar o Firestore: {e}", parent=lista_window)
                    continue

            messagebox.showinfo("Conclusão", "Arquivos enviados ao Firebase Storage e Firestore atualizados com sucesso.", parent=lista_window)
            botao_enviar.config(state='normal')  # Re-enable the button after completion

        threading.Thread(target=task).start()

    # Function to return to the input window
    def voltar():
        lista_window.destroy()
        abrir_janela_entrada()

    # Function to play the audio of the selected phrase
    def play_audio():
        selected_item = tree.selection()
        if not selected_item:
            messagebox.showwarning(
                "Aviso", "Por favor, selecione uma frase para ouvir o áudio.", parent=lista_window)
            return
        item_id = selected_item[0]
        idx = int(tree.item(item_id, 'values')[0])  # Número da frase
        status = tree.item(item_id, 'values')[3]
        if status != 'Sucesso':
            messagebox.showwarning(
                "Aviso", "Áudio ainda não foi gerado para esta frase.", parent=lista_window)
            return
        audio_filename = f"{base_name}-frase-{idx}.mp3"
        audio_filepath = os.path.join('audios', audio_filename)
        if not os.path.exists(audio_filepath):
            messagebox.showerror(
                "Erro", f"O arquivo de áudio '{audio_filename}' não foi encontrado.", parent=lista_window)
            return
        # Obter o caminho absoluto do arquivo de áudio
        audio_filepath = os.path.abspath(audio_filepath)

        # Reproduzir o áudio em uma thread separada
        def play():
            try:
                # Inicializar o mixer do Pygame
                pygame.mixer.init()
                # Carregar o arquivo de áudio
                pygame.mixer.music.load(audio_filepath)
                # Iniciar a reprodução
                pygame.mixer.music.play()
                # Loop para manter a reprodução ativa
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
                # Finalizar o mixer após a reprodução
                pygame.mixer.quit()
            except Exception as e:
                # Registrar o erro no console para depuração
                print(f"Erro ao reproduzir o áudio: {e}")

        threading.Thread(target=play).start()




    # Function to re-generate the audio of the selected phrase
    def re_generate_audio():
        selected_item = tree.selection()
        if not selected_item:
            messagebox.showwarning("Aviso", "Por favor, selecione uma frase para re-gerar o áudio.", parent=lista_window)
            return
        item_id = selected_item[0]
        idx = int(tree.item(item_id, 'values')[0])  # Number
        frase = tree.item(item_id, 'values')[1]
        # Re-generate audio for this phrase
        def task():
            audio_filepath = gerar_audio_e_legenda(frase, 'audios', base_name, idx)
            if audio_filepath:
                status = 'Sucesso'
                # Change status color to green
                tree.tag_configure('sucesso', foreground='green')
                values = list(tree.item(item_id, 'values'))
                values[3] = status  # Update 'Status'
                tree.item(item_id, values=values, tags=('sucesso',))
                messagebox.showinfo("Concluído", f"Áudio re-gerado para a frase {idx}.", parent=lista_window)
            else:
                status = 'Falha'
                # Change status color to red
                tree.tag_configure('falha', foreground='red')
                values = list(tree.item(item_id, 'values'))
                values[3] = status  # Update 'Status'
                tree.item(item_id, values=values, tags=('falha',))
                messagebox.showerror("Erro", f"Falha ao re-gerar o áudio para a frase {idx}.", parent=lista_window)
        threading.Thread(target=task).start()

    # Action buttons
    botao_adicionar = tk.Button(frame_botoes, text="Adicionar", width=15, command=adicionar_frase, bg='#4CAF50', fg='white', font=('Helvetica', 10, 'bold'), relief='raised')
    botao_adicionar.grid(row=0, column=0, padx=10, pady=5)

    botao_editar = tk.Button(frame_botoes, text="Editar", width=15, command=editar_frase, bg='#2196F3', fg='white', font=('Helvetica', 10, 'bold'), relief='raised')
    botao_editar.grid(row=0, column=1, padx=10, pady=5)

    botao_apagar = tk.Button(frame_botoes, text="Apagar", width=15, command=apagar_frase, bg='#f44336', fg='white', font=('Helvetica', 10, 'bold'), relief='raised')
    botao_apagar.grid(row=0, column=2, padx=10, pady=5)

    botao_mover_cima = tk.Button(frame_botoes, text="Mover para Cima", width=15, command=mover_para_cima, bg='#FFC107', fg='white', font=('Helvetica', 10, 'bold'), relief='raised')
    botao_mover_cima.grid(row=0, column=3, padx=10, pady=5)

    botao_mover_baixo = tk.Button(frame_botoes, text="Mover para Baixo", width=15, command=mover_para_baixo, bg='#03A9F4', fg='white', font=('Helvetica', 10, 'bold'), relief='raised')
    botao_mover_baixo.grid(row=0, column=4, padx=10, pady=5)

    botao_gerar = tk.Button(frame_botoes, text="Gerar Áudio", width=15, command=gerar_audios_e_legendas, bg='#FF9800', fg='white', font=('Helvetica', 10, 'bold'), relief='raised')
    botao_gerar.grid(row=0, column=5, padx=10, pady=5)

    botao_enviar = tk.Button(frame_botoes, text="Enviar ao Firebase", width=20, command=enviar_ao_firebase, bg='#3F51B5', fg='white', font=('Helvetica', 10, 'bold'), relief='raised', state='disabled')
    botao_enviar.grid(row=0, column=6, padx=10, pady=5)

    botao_voltar = tk.Button(frame_botoes, text="Voltar", width=15, command=voltar, bg='#9E9E9E', fg='white', font=('Helvetica', 10, 'bold'), relief='raised')
    botao_voltar.grid(row=0, column=7, padx=10, pady=5)

    botao_play_audio = tk.Button(frame_botoes, text="Ouvir Áudio", width=15, command=play_audio, bg='#8BC34A', fg='white', font=('Helvetica', 10, 'bold'), relief='raised')
    botao_play_audio.grid(row=0, column=8, padx=10, pady=5)

    botao_regenerate = tk.Button(frame_botoes, text="Re-gerar Áudio", width=15, command=re_generate_audio, bg='#FF5722', fg='white', font=('Helvetica', 10, 'bold'), relief='raised')
    botao_regenerate.grid(row=0, column=9, padx=10, pady=5)

    lista_window.mainloop()

# Main function to open a larger text input window
def abrir_janela_entrada():
    janela = tk.Toplevel()
    janela.title("Entrada de Texto")
    janela.geometry("1280x720")  # Set window size

    # Apply theme
    style = ttk.Style(janela)
    style.theme_use('arc')  # You can choose other available themes

    # Style labels and entries
    style.configure("TLabel", font=('Helvetica', 12))
    style.configure("TEntry", font=('Helvetica', 11))
    style.configure("TButton", font=('Helvetica', 12, 'bold'))

    # Frame for text input
    frame_texto = tk.Frame(janela)
    frame_texto.pack(pady=20, padx=20, fill=tk.BOTH, expand=True)

    label = tk.Label(frame_texto, text="Digite o texto para conversão:", font=('Helvetica', 14, 'bold'))
    label.pack(pady=10)

    entrada = tk.Text(frame_texto, width=100, height=25, font=('Helvetica', 12), wrap='word')  # Increased size
    entrada.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    # Frame for base name
    frame_nome = tk.Frame(janela)
    frame_nome.pack(pady=10, padx=20, fill=tk.X)

    label_nome = tk.Label(frame_nome, text="Digite o nome base para os arquivos:", font=('Helvetica', 14, 'bold'))
    label_nome.pack(side=tk.LEFT, padx=5, pady=5)

    entrada_nome = tk.Entry(frame_nome, width=60, font=('Helvetica', 12))  # Increased size
    entrada_nome.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X, expand=True)

    # Frame for buttons
    frame_botoes = tk.Frame(janela)
    frame_botoes.pack(pady=20)

    # Function to confirm the text and start processing
    def confirmar_texto():
        texto = entrada.get("1.0", tk.END).strip()
        base_name = entrada_nome.get().strip()
        if texto and base_name:
            janela.destroy()
            iniciar_processamento(texto, base_name)
        else:
            messagebox.showinfo("Aviso", "Por favor, insira o texto e o nome base para os arquivos.", parent=janela)

    # Function to cancel the operation
    def cancelar():
        janela.destroy()
        messagebox.showinfo("Cancelado", "A operação foi cancelada.", parent=janela)

    # OK Button
    botao_ok = tk.Button(frame_botoes, text="OK", width=20, command=confirmar_texto, bg='#4CAF50', fg='white', font=('Helvetica', 12, 'bold'), relief='raised')
    botao_ok.grid(row=0, column=0, padx=20, pady=10)

    # Cancel Button
    botao_cancelar = tk.Button(frame_botoes, text="Cancelar", width=20, command=cancelar, bg='#f44336', fg='white', font=('Helvetica', 12, 'bold'), relief='raised')
    botao_cancelar.grid(row=0, column=1, padx=20, pady=10)

    janela.mainloop()

# Run the program
if __name__ == "__main__":
    # Uncomment the line below to list available voices
    # obter_vozes_disponiveis()

    root = ThemedTk(theme="arc")  # Using a modern theme
    root.withdraw()
    abrir_janela_entrada()
