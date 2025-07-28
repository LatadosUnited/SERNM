# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import filedialog, Listbox, Toplevel, Text
from tkinter import messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
import os
import json
import shutil
import glob
from datetime import datetime
import locale
import threading
import logging
from logging.handlers import RotatingFileHandler
import queue
from pathlib import Path

# Tenta importar dependências específicas; falha graciosamente se não encontradas.
try:
    from validate_docbr import CNPJ
    CNPJ_VALIDATOR = CNPJ()
    VALIDATE_DOCBR_AVAILABLE = True
except ImportError:
    VALIDATE_DOCBR_AVAILABLE = False
    CNPJ_VALIDATOR = None
    print("AVISO: Biblioteca 'validate_docbr' não encontrada. A validação de CNPJ estará desativada.")

try:
    from icone_data import icone_base64
except ImportError:
    icone_base64 = None

# --- DEFINIÇÃO DOS DIRETÓRIOS DE DADOS DA APLICAÇÃO ---
APP_NAME = "SistemaUnificado"
AUTHOR = "Florest"
try:
    APP_DATA_DIR = Path(os.getenv('APPDATA')) / AUTHOR / APP_NAME
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    print(f"AVISO: Não foi possível criar o diretório em AppData ({e}). Usando diretório local.")
    APP_DATA_DIR = Path(os.getcwd())

# Subpastas e arquivos de configuração
SERN_DATA_DIR = APP_DATA_DIR / "SERN_Data"
MANIFEST_DATA_DIR = APP_DATA_DIR / "Manifest_Data"
APP_CONFIG_FILE = APP_DATA_DIR / "app_config.json"
SERN_DATA_DIR.mkdir(exist_ok=True)
MANIFEST_DATA_DIR.mkdir(exist_ok=True)

# --- CONFIGURAÇÃO INICIAL DO LOGGING ---
log_file = SERN_DATA_DIR / 'sistema_unificado.log'
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler = RotatingFileHandler(log_file, maxBytes=1*1024*1024, backupCount=1, encoding='utf-8')
file_handler.setFormatter(log_formatter)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
if logger.hasHandlers(): logger.handlers.clear()
logger.addHandler(file_handler)
# --- FIM DA CONFIGURAÇÃO DO LOGGING ---

try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except locale.Error:
    logging.warning("Locale 'pt_BR' não pôde ser configurado.")

# ############################################################################
#
#   MÓDULO 1: SERN - SEPARADOR E ORGANIZADOR DE NOTAS
#
# ############################################################################

class SernFrame(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, padding=10, **kwargs)
        self.master = master
        self.CONFIG_FILE = SERN_DATA_DIR / 'config.json'
        self.DEFAULT_BASE_PATH = os.path.join("C:\\", "Docfinder", "XML")

        self.root_folder_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.update_display())
        
        self.progress_queue = queue.Queue()
        self.last_scan_results = []
        self.settings = self.load_settings()

        self._create_widgets()
        self.configure_logging_text_widget()
        self.suggest_daily_folder()
        logging.info("Módulo SERN (Organizador de Notas) carregado.")
        logging.info(f"Arquivos de configuração e log do SERN estão em: {SERN_DATA_DIR}")

    def configure_logging_text_widget(self):
        text_handler = TextWidgetHandler(self.log_text)
        text_handler.setFormatter(logging.Formatter('%(message)s'))
        if not any(isinstance(h, TextWidgetHandler) for h in logger.handlers):
            logger.addHandler(text_handler)
        
    def load_settings(self):
        if not os.path.exists(self.CONFIG_FILE): return {"base_path": self.DEFAULT_BASE_PATH, "companies": []}
        try:
            with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content: return {"base_path": self.DEFAULT_BASE_PATH, "companies": []}
                settings = json.loads(content)
            
            settings.setdefault("base_path", self.DEFAULT_BASE_PATH)
            settings.setdefault("companies", [])
            
            migrated = False
            for company in settings["companies"]:
                if "cnpj" in company and "cnpjs" not in company:
                    company["cnpjs"] = [company["cnpj"]]; del company["cnpj"]; migrated = True
            if migrated:
                logging.info("Configuração antiga detectada, migrando para novo formato de múltiplos CNPJs.")
                self.save_settings(settings)
            return settings
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logging.error(f"Erro ao carregar configurações do SERN: {e}"); return {"base_path": self.DEFAULT_BASE_PATH, "companies": []}

    def save_settings(self, settings_to_save=None):
        data_to_save = settings_to_save if settings_to_save is not None else self.settings
        tmp_file = str(self.CONFIG_FILE) + '.tmp'
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f: json.dump(data_to_save, f, indent=4, ensure_ascii=False)
            os.replace(tmp_file, self.CONFIG_FILE)
            logging.info("Configurações do SERN salvas com segurança!")
        except (IOError, OSError) as e:
            logging.error(f"Falha crítica ao salvar configurações do SERN: {e}")
            if os.path.exists(tmp_file): os.remove(tmp_file)

    def suggest_daily_folder(self):
        now = datetime.now()
        year, month, day = now.strftime("%Y"), now.strftime("%B").upper(), now.strftime("%d")
        base_path = self.settings.get("base_path", self.DEFAULT_BASE_PATH)
        daily_path = os.path.join(base_path, year, month, day)
        self.root_folder_var.set(daily_path)
        logging.info(f"Pasta raiz sugerida: {daily_path}")
        self.scan_and_display_companies()

    def _create_widgets(self):
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        root_frame = ttk.LabelFrame(self, text="1. Pasta Raiz das Notas", padding="10")
        root_frame.grid(row=0, column=0, sticky="ew", pady=5)
        root_frame.columnconfigure(0, weight=1)
        ttk.Entry(root_frame, textvariable=self.root_folder_var).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(root_frame, text="Procurar...", command=self.browse_root_folder, bootstyle="outline").grid(row=0, column=1)

        search_frame = ttk.LabelFrame(self, text="Procurar Empresa por Nome", padding="10")
        search_frame.grid(row=1, column=0, sticky="ew", pady=5)
        search_frame.columnconfigure(0, weight=1)
        ttk.Entry(search_frame, textvariable=self.search_var).grid(row=0, column=0, sticky="ew")

        list_container = ttk.LabelFrame(self, text="Lista de Empresas", padding="10")
        list_container.grid(row=2, column=0, sticky="nsew", pady=5)
        list_container.columnconfigure(0, weight=1)
        list_container.rowconfigure(0, weight=1)
        
        canvas = tk.Canvas(list_container, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.scrollable_frame.columnconfigure(0, weight=1)

        self.progress_frame = ttk.Frame(self, padding=(0, 10))
        self.progress_frame.grid(row=3, column=0, sticky="ew")
        self.progress_frame.columnconfigure(0, weight=1)
        self.progress_label = ttk.Label(self.progress_frame, text="Pronto.")
        self.progress_label.grid(row=0, column=0, sticky="w")
        self.progressbar = ttk.Progressbar(self.progress_frame, bootstyle="success-striped")
        self.progressbar.grid(row=1, column=0, sticky="ew")
        self.progress_frame.grid_remove()

        log_frame = ttk.LabelFrame(self, text="Log de Atividades (e em sistema_unificado.log)", padding="10")
        log_frame.grid(row=4, column=0, sticky="ew", pady=5)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=8, state='disabled', wrap='word', relief="sunken", borderwidth=1)
        log_scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text['yscrollcommand'] = log_scrollbar.set
        self.log_text.grid(row=0, column=0, sticky="ew")
        log_scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.tag_configure("INFO", foreground="#198754")
        self.log_text.tag_configure("WARNING", foreground="#fd7e14")
        self.log_text.tag_configure("ERROR", foreground="#dc3545")
        self.log_text.tag_configure("NORMAL", foreground="black")

    def browse_root_folder(self):
        folder = filedialog.askdirectory(initialdir=self.root_folder_var.get())
        if folder:
            self.root_folder_var.set(folder)
            logging.info(f"Pasta raiz alterada: {folder}")
            self.scan_and_display_companies()

    def update_display(self):
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        search_term = self.search_var.get().lower()
        display_list = [c for c in self.last_scan_results if search_term in c['name'].lower()] if search_term else self.last_scan_results
        if not display_list and self.last_scan_results:
            ttk.Label(self.scrollable_frame, text="Nenhuma empresa encontrada com este nome.").pack(pady=10)
        for company_data in display_list:
            self.create_company_row(company_data)

    def scan_and_display_companies(self):
        threading.Thread(target=self._execute_scan, daemon=True).start()

    def _execute_scan(self):
        self.after(0, lambda: self.master.master.toggle_ui_state(False))
        self.last_scan_results = []
        self.after(0, self.update_display)
        root_folder = self.root_folder_var.get()
        if not os.path.isdir(root_folder):
            logging.warning(f"A pasta {root_folder} não foi encontrada.")
            self.after(0, lambda: self.master.master.toggle_ui_state(True))
            return
        if not self.settings["companies"]:
            logging.info("Nenhuma empresa configurada no SERN.")
            self.after(0, lambda: self.master.master.toggle_ui_state(True))
            return
        logging.info(f"Verificando arquivos em: {root_folder}")
        try:
            all_filenames = os.listdir(root_folder)
        except Exception as e:
            logging.error(f"Não foi possível ler a pasta: {e}")
            self.after(0, lambda: self.master.master.toggle_ui_state(True))
            return
        
        company_counts = {c['name']: 0 for c in self.settings['companies']}
        for filename in all_filenames:
            for company in self.settings['companies']:
                if any(cnpj in filename for cnpj in company.get('cnpjs', [])):
                    company_counts[company['name']] += 1
                    break
        
        temp_results = [dict(c, notes_count=company_counts.get(c['name'], 0)) for c in self.settings["companies"]]
        self.last_scan_results = sorted(temp_results, key=lambda x: x['name'])
        logging.info("Verificação concluída.")
        self.after(0, self.update_display)
        self.after(0, lambda: self.master.master.toggle_ui_state(True))

    def create_company_row(self, company_data):
        row_frame = ttk.Frame(self.scrollable_frame, padding=5, bootstyle="light", relief="solid", borderwidth=1)
        row_frame.pack(fill=tk.X, pady=4, padx=5)
        row_frame.columnconfigure(0, weight=1)
        
        info_frame = ttk.Frame(row_frame)
        info_frame.grid(row=0, column=0, sticky="w")
        ttk.Label(info_frame, text=company_data['name'], font=('Segoe UI', 10, 'bold')).pack(anchor="w")
        ttk.Label(info_frame, text=f"CNPJs: {', '.join(company_data.get('cnpjs', []))}", bootstyle="secondary").pack(anchor="w")
        ttk.Label(info_frame, text=f"Notas encontradas: {company_data['notes_count']}", bootstyle="primary", font=('Segoe UI', 9, 'bold')).pack(anchor="w")
        
        button_frame = ttk.Frame(row_frame)
        button_frame.grid(row=0, column=1, sticky="e")
        
        transfer_button = ttk.Button(button_frame, text="Transferir", bootstyle="success", command=lambda c=company_data: self.transfer_files_for_company(c))
        transfer_button.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)
        
        open_folder_button = ttk.Button(button_frame, text="Abrir Pasta", bootstyle="outline-secondary", command=lambda p=company_data['dest_folder']: self.open_folder(p))
        open_folder_button.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)

        clean_button = ttk.Button(button_frame, text="Limpar Pasta", bootstyle="danger-outline", command=lambda c=company_data: self.clean_company_folder(c))
        clean_button.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)
        
        if company_data['notes_count'] == 0:
            transfer_button.config(state="disabled")

    def open_folder(self, path):
        try:
            if os.path.isdir(path):
                logging.info(f"Abrindo pasta: {path}")
                os.startfile(path)
            else:
                logging.warning(f"Tentativa de abrir pasta inexistente: {path}")
                Messagebox.show_warning(f"O caminho '{path}' não existe ou não é uma pasta.", "Pasta não encontrada", parent=self)
        except Exception as e:
            logging.error(f"Não foi possível abrir a pasta '{path}': {e}")
            Messagebox.show_error(f"Não foi possível abrir a pasta '{path}'.\nErro: {e}", "Erro ao Abrir", parent=self)

    def transfer_files_for_company(self, config):
        self.master.master.toggle_ui_state(False)
        self.progress_frame.grid()
        self.progressbar['value'] = 0
        threading.Thread(target=self._execute_transfer, args=(config,), daemon=True).start()
        self.after(100, self.check_progress_queue)

    def _execute_transfer(self, config):
        root_folder = self.root_folder_var.get()
        company_name, cnpjs, dest_folder = config['name'], config.get('cnpjs',[]), config['dest_folder']
        logging.info(f"Iniciando transferência para: {company_name}")
        try:
            os.makedirs(dest_folder, exist_ok=True)
        except OSError as e:
            logging.error(f"Não foi possível criar pasta de destino '{dest_folder}': {e}")
            self.progress_queue.put("done")
            return
        
        files_to_copy = sorted(list(set(f for cnpj in cnpjs for f in glob.glob(os.path.join(root_folder, f"*{cnpj}*")))))
        if not files_to_copy:
            logging.warning("Nenhum arquivo encontrado para transferência.")
            self.progress_queue.put("done")
            return

        total_files = len(files_to_copy)
        for i, source_path in enumerate(files_to_copy):
            self.progress_queue.put({"current": i + 1, "total": total_files})
            file_name = os.path.basename(source_path)
            try:
                shutil.copy2(source_path, os.path.join(dest_folder, file_name))
            except Exception as e:
                logging.error(f"Erro ao copiar '{file_name}': {e}")
        logging.info(f"Transferência para {company_name} concluída.")
        self.progress_queue.put("done")

    def check_progress_queue(self):
        try:
            message = self.progress_queue.get_nowait()
            if isinstance(message, dict):
                self.progressbar['maximum'] = message['total']
                self.progressbar['value'] = message['current']
                self.progress_label.config(text=f"Copiando {message['current']} de {message['total']}...")
                self.after(100, self.check_progress_queue)
            elif message == "done":
                self.progress_label.config(text="Transferência Concluída!")
                self.on_operation_complete()
        except queue.Empty:
            self.after(100, self.check_progress_queue)

    def on_operation_complete(self):
        self.scan_and_display_companies() 
        self.after(2000, lambda: self.progress_frame.grid_remove())

    def clean_company_folder(self, company_data):
        dest_folder = company_data['dest_folder']
        company_name = company_data['name']
        confirm_message = (f"Tem certeza que deseja apagar TODOS os arquivos da pasta para a empresa '{company_name}'?\n\n"
                           f"Pasta: {dest_folder}\n\nEsta ação não pode ser desfeita.")
        if not Messagebox.yesno(confirm_message, "⚠️ Confirmar Limpeza", parent=self):
            return
        logging.info(f"Iniciando limpeza da pasta de destino para '{company_name}': {dest_folder}")
        if not os.path.isdir(dest_folder):
            Messagebox.show_warning(f"A pasta '{dest_folder}' não foi encontrada!", "Pasta Inexistente", parent=self)
            return
        deleted_count, error_count = 0, 0
        try:
            for filename in os.listdir(dest_folder):
                file_path = os.path.join(dest_folder, filename)
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                    except OSError as e:
                        logging.error(f"Não foi possível remover o arquivo {file_path}: {e}")
                        error_count += 1
        except Exception as e:
            Messagebox.show_error(f"Ocorreu um erro ao tentar limpar a pasta:\n{e}", "Erro Crítico", parent=self)
            return
        final_message = f"Limpeza concluída para '{company_name}'.\nArquivos removidos: {deleted_count}."
        if error_count > 0: final_message += f"\nFalhas ao remover: {error_count}."
        Messagebox.show_info(final_message, "Limpeza Concluída", parent=self)

    def clean_all_company_folders(self):
        if not self.settings['companies']:
            Messagebox.show_info("Nenhuma empresa está configurada. Nada a fazer.", "Aviso", parent=self)
            return
        confirm_message = ("ATENÇÃO!\n\nVocê tem certeza que deseja apagar TODOS os arquivos de TODAS as pastas de destino configuradas?\n\n"
                           "Esta ação é irreversível e afetará todas as empresas.")
        if not Messagebox.yesno(confirm_message, "☢️ CONFIRMAÇÃO DE LIMPEZA GERAL ☢️", parent=self):
            return
        logging.info("Iniciando limpeza geral de todas as pastas de destino configuradas.")
        total_files_deleted, total_errors, folders_processed = 0, 0, 0
        for company in self.settings['companies']:
            dest_folder = company['dest_folder']
            if os.path.isdir(dest_folder):
                folders_processed += 1
                try:
                    for filename in os.listdir(dest_folder):
                        file_path = os.path.join(dest_folder, filename)
                        if os.path.isfile(file_path):
                            try:
                                os.remove(file_path)
                                total_files_deleted += 1
                            except OSError as e:
                                logging.error(f"Não foi possível remover o arquivo {file_path}: {e}")
                                total_errors += 1
                except Exception as e:
                    logging.error(f"Erro inesperado ao acessar a pasta {dest_folder}: {e}")
                    total_errors += 1
        final_message = (f"Limpeza geral concluída!\n\nPastas processadas: {folders_processed}\nTotal de arquivos removidos: {total_files_deleted}")
        if total_errors > 0: final_message += f"\nErros encontrados: {total_errors} (verifique o log para detalhes)."
        Messagebox.show_info(final_message, "Limpeza Geral Concluída", parent=self)
    
    def open_config_window(self):
        ConfigWindow(master=self, app_master=self.master.master)

# ############################################################################
#
#   MÓDULO 2: GERADOR DE MANIFESTO
#
# ############################################################################

class ManifestFrame(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, padding=20, **kwargs)
        self.master = master
        self.CONFIG_FILE = MANIFEST_DATA_DIR / "config.json"
        self.DEFAULT_TEMPLATE_NAME = "Aviso de Entrega Padrão"
        self.DEFAULT_TEMPLATE_CONTENT = "AVISO: O motorista [NOME DO MOTORISTA] com o carro de placa [PLACA DO CARRO] está a caminho para realizar a entrega."
        
        self.app_data = self.load_data()
        self._create_widgets()
        self.update_driver_menu()
        self.update_template_menu()
        logging.info("Módulo Gerador de Manifesto carregado.")

    def load_data(self):
        try:
            with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f: dados = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            dados = {"drivers": [], "templates": {}}
        if isinstance(dados.get("drivers"), dict):
            dados["drivers"] = sorted(list(dados["drivers"].keys()))
        if "drivers" not in dados: dados["drivers"] = []
        if "templates" not in dados or not dados["templates"]:
            dados["templates"] = {self.DEFAULT_TEMPLATE_NAME: self.DEFAULT_TEMPLATE_CONTENT}
        return dados

    def save_data(self):
        self.app_data["drivers"] = sorted(list(set(self.app_data["drivers"])))
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.app_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Falha ao salvar dados do manifesto: {e}")

    def _create_widgets(self):
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="1. Selecione o Texto Base:", font=("Segoe UI", 12)).pack(anchor="w", fill="x")
        self.template_var = tk.StringVar(self)
        self.template_menu = ttk.OptionMenu(self, self.template_var, "Carregando...")
        self.template_menu.pack(fill="x", pady=(5, 15), ipady=5)
        ttk.Label(self, text="2. Selecione o Motorista:", font=("Segoe UI", 12)).pack(anchor="w", fill="x")
        self.driver_var = tk.StringVar(self)
        self.driver_menu = ttk.OptionMenu(self, self.driver_var, "Carregando...")
        self.driver_menu.pack(fill="x", pady=(5, 15), ipady=5)
        ttk.Label(self, text="3. Digite a Placa do Veículo:", font=("Segoe UI", 12)).pack(anchor="w", fill="x")
        self.plate_var = tk.StringVar(self)
        plate_entry = ttk.Entry(self, textvariable=self.plate_var, font=("Segoe UI", 11))
        plate_entry.pack(fill="x", pady=(5, 20), ipady=5)
        generate_button = ttk.Button(self, text="Gerar Texto Final", command=self.generate_final_text, bootstyle="success")
        generate_button.pack(fill="x", ipady=8, pady=(0, 20))

        result_frame = ttk.Frame(self)
        result_frame.pack(fill="both", expand=True)
        result_frame.columnconfigure(0, weight=1)
        
        label_frame = ttk.Frame(result_frame)
        label_frame.pack(fill='x')
        ttk.Label(label_frame, text="Resultado:", font=("Segoe UI", 12)).pack(side='left')
        self.copy_button = ttk.Button(label_frame, text="Copiar", bootstyle="outline-toolbutton", command=self.copy_result_to_clipboard)
        self.copy_button.pack(side='left', padx=10)
        self.copy_button.pack_forget() # Hide it initially

        self.result_text = Text(result_frame, height=5, font=("Segoe UI", 11), state=tk.DISABLED, relief="sunken", borderwidth=1, wrap=tk.WORD, padx=5, pady=5)
        self.result_text.pack(fill="both", expand=True, pady=(5, 20))
        management_frame = ttk.Frame(self)
        management_frame.pack(fill='x', side='bottom')
        management_frame.columnconfigure((0, 1), weight=1)
        
        manage_templates_button = ttk.Button(management_frame, text="Gerenciar Textos", command=self.open_manage_templates_window, bootstyle="secondary")
        manage_templates_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        manage_drivers_button = ttk.Button(management_frame, text="Gerenciar Motoristas", command=self.open_manage_drivers_window, bootstyle="secondary")
        manage_drivers_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))

    def copy_result_to_clipboard(self):
        text_to_copy = self.result_text.get("1.0", tk.END).strip()
        if not text_to_copy: return
        self.clipboard_clear()
        self.clipboard_append(text_to_copy)
        
        original_text = self.copy_button.cget("text")
        self.copy_button.config(text="Copiado!", bootstyle="success-toolbutton")
        self.after(1500, lambda: self.copy_button.config(text=original_text, bootstyle="outline-toolbutton"))

    def generate_final_text(self):
        driver = self.driver_var.get()
        plate = self.plate_var.get().strip().upper()
        template_name = self.template_var.get()

        if template_name in ["Nenhum texto cadastrado", "Carregando..."] or not template_name:
            Messagebox.show_warning("Por favor, cadastre ou selecione um texto base.", "Atenção", parent=self)
            return
        if driver in ["Selecione um motorista", "Carregando..."] or not driver:
            Messagebox.show_warning("Por favor, selecione um motorista.", "Atenção", parent=self)
            return
        if not plate:
            Messagebox.show_warning("O campo da placa não pode estar vazio.", "Atenção", parent=self)
            return

        base_text = self.app_data["templates"].get(template_name, "")
        final_text = base_text.replace("[NOME DO MOTORISTA]", driver).replace("[PLACA DO CARRO]", plate)

        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert(tk.END, final_text)
        self.result_text.config(state=tk.DISABLED)
        self.copy_button.pack(side='left', padx=10) # Show the copy button

    def update_driver_menu(self):
        menu = self.driver_menu['menu']
        menu.delete(0, 'end')
        drivers = ["Selecione um motorista"] + self.app_data["drivers"]
        for d in drivers: menu.add_command(label=d, command=tk._setit(self.driver_var, d))
        self.driver_var.set(drivers[0])

    def update_template_menu(self):
        menu = self.template_menu['menu']
        menu.delete(0, 'end')
        templates = sorted(list(self.app_data["templates"].keys()))
        if not templates: self.template_var.set("Nenhum texto cadastrado")
        else:
            for t in templates: menu.add_command(label=t, command=tk._setit(self.template_var, t))
            self.template_var.set(templates[0])

    def open_manage_drivers_window(self):
        ManageDriversWindow(master=self, app_master=self.master.master)

    def open_manage_templates_window(self):
        ManageTemplatesWindow(master=self, app_master=self.master.master)

# ############################################################################
#
#   JANELAS AUXILIARES
#
# ############################################################################

class TextWidgetHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.tag_map = {"INFO": "INFO", "WARNING": "WARNING", "ERROR": "ERROR", "CRITICAL": "ERROR"}
    def emit(self, record):
        msg = self.format(record)
        tag = self.tag_map.get(record.levelname, "NORMAL")
        self.text_widget.after(0, lambda: self.append_message(msg, tag))
    def append_message(self, msg, tag):
        self.text_widget.config(state='normal')
        self.text_widget.insert(tk.END, msg + '\n', tag)
        self.text_widget.config(state='disabled')
        self.text_widget.see(tk.END)

class ConfigWindow(Toplevel):
    def __init__(self, master, app_master):
        super().__init__(app_master)
        self.sern_master = master
        self.title("Gerenciar Empresas (SERN)"); self.geometry("800x600"); self.transient(app_master); self.grab_set()
        self.base_path_var = tk.StringVar(value=self.sern_master.settings.get("base_path"))
        self.company_name_var = tk.StringVar(); self.cnpjs_var = tk.StringVar(); self.dest_folder_var = tk.StringVar()
        self.editing_company_name = None; self.cnpj_validator = CNPJ_VALIDATOR
        self._create_widgets(); self.refresh_treeview(); self.protocol("WM_DELETE_WINDOW", self.save_and_close)
    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding="10"); main_frame.pack(fill=tk.BOTH, expand=True)
        general_frame = ttk.LabelFrame(main_frame, text="Configurações Gerais do SERN", padding="10"); general_frame.pack(fill=tk.X, pady=5)
        ttk.Label(general_frame, text="Caminho Base (Leitura):").pack(side=tk.LEFT, padx=(0,5))
        ttk.Entry(general_frame, textvariable=self.base_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.form_frame = ttk.LabelFrame(main_frame, text="Adicionar Nova Empresa", padding="10"); self.form_frame.pack(fill=tk.X, pady=5)
        self.form_frame.columnconfigure(1, weight=1)
        ttk.Label(self.form_frame, text="Nome da Empresa:").grid(row=0, column=0, sticky="ew", padx=5, pady=3)
        ttk.Entry(self.form_frame, textvariable=self.company_name_var).grid(row=0, column=1, columnspan=2, sticky="ew", padx=5, pady=3)
        ttk.Label(self.form_frame, text="CNPJs (separados por vírgula):").grid(row=1, column=0, sticky="ew", padx=5, pady=3)
        ttk.Entry(self.form_frame, textvariable=self.cnpjs_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=5, pady=3)
        ttk.Label(self.form_frame, text="Pasta de Destino:").grid(row=2, column=0, sticky="ew", padx=5, pady=3)
        ttk.Entry(self.form_frame, textvariable=self.dest_folder_var).grid(row=2, column=1, sticky="ew", padx=5, pady=3)
        ttk.Button(self.form_frame, text="Procurar...", command=self.browse_dest_folder, bootstyle="outline").grid(row=2, column=2, padx=5, pady=3)
        self.form_button_frame = ttk.Frame(self.form_frame); self.form_button_frame.grid(row=3, column=0, columnspan=3, pady=10)
        self.add_button = ttk.Button(self.form_button_frame, text="Adicionar Empresa", command=self.add_config, bootstyle="success"); self.add_button.pack(side=tk.LEFT, padx=5)
        self.save_edit_button = ttk.Button(self.form_button_frame, text="Salvar Alterações", command=self.save_edit, state="disabled", bootstyle="primary"); self.save_edit_button.pack(side=tk.LEFT, padx=5)
        self.cancel_edit_button = ttk.Button(self.form_button_frame, text="Cancelar Edição", command=self.cancel_edit, state="disabled", bootstyle="secondary"); self.cancel_edit_button.pack(side=tk.LEFT, padx=5)
        list_frame = ttk.LabelFrame(main_frame, text="Empresas Configradas", padding="10"); list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        columns = ("name", "cnpjs", "dest_folder"); self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", bootstyle="primary")
        self.tree.heading("name", text="Nome"); self.tree.heading("cnpjs", text="CNPJs"); self.tree.heading("dest_folder", text="Pasta de Destino")
        self.tree.column("cnpjs", width=250); self.tree.column("dest_folder", width=300); self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview, bootstyle="round"); self.tree.configure(yscrollcommand=scrollbar.set); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        list_action_frame = ttk.Frame(main_frame); list_action_frame.pack(pady=5)
        ttk.Button(list_action_frame, text="Editar Selecionada", command=self.edit_selected, bootstyle="info-outline").pack(side=tk.LEFT, padx=5)
        ttk.Button(list_action_frame, text="Remover Selecionada", command=self.remove_config, bootstyle="danger-outline").pack(side=tk.LEFT, padx=5)
        ttk.Button(main_frame, text="✅ Salvar e Fechar", command=self.save_and_close, bootstyle="primary").pack(pady=10, ipady=5)
    def browse_dest_folder(self):
        folder = filedialog.askdirectory(parent=self);
        if folder: self.dest_folder_var.set(folder)
    def refresh_treeview(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        for config in sorted(self.sern_master.settings["companies"], key=lambda c: c['name']): self.tree.insert("", tk.END, values=(config['name'], ", ".join(config.get('cnpjs', [])), config['dest_folder']))
    def get_cnpjs_from_input(self): return [cnpj.strip() for cnpj in self.cnpjs_var.get().split(',') if cnpj.strip()]
    def validate_and_save(self, name, cnpjs, dest, is_editing=False):
        if not all([name, cnpjs, dest]): Messagebox.show_error("Todos os campos são obrigatórios.", "Erro", parent=self); return False
        if VALIDATE_DOCBR_AVAILABLE:
            for cnpj in cnpjs:
                if not self.cnpj_validator.validate(cnpj): Messagebox.show_error(f"O CNPJ '{cnpj}' é inválido!", "Erro de Validação", parent=self); return False
        other_companies = [c for c in self.sern_master.settings["companies"] if is_editing and c['name'] != self.editing_company_name or not is_editing]
        if any(c['name'].lower() == name.lower() for c in other_companies): Messagebox.show_error(f"O nome de empresa '{name}' já existe.", "Erro de Duplicidade", parent=self); return False
        all_other_cnpjs = {other_cnpj for company in other_companies for other_cnpj in company.get('cnpjs', [])}
        for cnpj in cnpjs:
            if cnpj in all_other_cnpjs: Messagebox.show_error(f"O CNPJ '{cnpj}' já está em uso por outra empresa!", "Erro de Duplicidade", parent=self); return False
        return True
    def add_config(self):
        name, dest, cnpjs = self.company_name_var.get().strip(), self.dest_folder_var.get().strip(), self.get_cnpjs_from_input()
        if self.validate_and_save(name, cnpjs, dest):
            self.sern_master.settings["companies"].append({"name": name, "cnpjs": cnpjs, "dest_folder": dest}); self.sern_master.save_settings()
            self.refresh_treeview(); self.clear_entries(); logging.info(f"Empresa '{name}' adicionada.")
    def remove_config(self):
        if not self.tree.selection(): return
        if Messagebox.yesno("Tem certeza que deseja remover a empresa selecionada?", "Confirmar Remoção", parent=self):
            selected_name = self.tree.item(self.tree.selection()[0])['values'][0]
            self.sern_master.settings["companies"] = [c for c in self.sern_master.settings["companies"] if c['name'] != selected_name]
            self.sern_master.save_settings(); self.refresh_treeview(); logging.info(f"Empresa '{selected_name}' foi removida.")
    def edit_selected(self):
        if not self.tree.selection(): return
        self.editing_company_name = self.tree.item(self.tree.selection()[0])['values'][0]
        company = next(c for c in self.sern_master.settings["companies"] if c['name'] == self.editing_company_name)
        self.company_name_var.set(company['name']); self.cnpjs_var.set(", ".join(company.get('cnpjs', []))); self.dest_folder_var.set(company['dest_folder'])
        self.form_frame.config(text=f"Editando: {company['name']}"); self.add_button.config(state="disabled"); self.save_edit_button.config(state="normal"); self.cancel_edit_button.config(state="normal")
    def save_edit(self):
        new_name, new_dest, new_cnpjs = self.company_name_var.get().strip(), self.dest_folder_var.get().strip(), self.get_cnpjs_from_input()
        if self.validate_and_save(new_name, new_cnpjs, new_dest, is_editing=True):
            for company in self.sern_master.settings["companies"]:
                if company['name'] == self.editing_company_name: company.update({"name": new_name, "cnpjs": new_cnpjs, "dest_folder": new_dest}); break
            self.sern_master.save_settings(); logging.info(f"Empresa '{self.editing_company_name}' foi atualizada para '{new_name}'."); self.refresh_treeview(); self.cancel_edit()
    def cancel_edit(self):
        self.editing_company_name = None; self.clear_entries()
        self.form_frame.config(text="Adicionar Nova Empresa"); self.add_button.config(state="normal"); self.save_edit_button.config(state="disabled"); self.cancel_edit_button.config(state="disabled")
    def clear_entries(self): self.company_name_var.set(""); self.cnpjs_var.set(""); self.dest_folder_var.set("")
    def save_and_close(self):
        if self.editing_company_name: self.cancel_edit()
        self.sern_master.settings["base_path"] = self.base_path_var.get(); self.sern_master.save_settings(); self.destroy(); self.sern_master.suggest_daily_folder()

class ManageDriversWindow(Toplevel):
    def __init__(self, master, app_master):
        super().__init__(app_master)
        self.manifest_master = master; self.title("Gerenciar Motoristas"); self.geometry("450x350"); self.transient(app_master); self.grab_set()
        frame_gerenciar = ttk.Frame(self, padding=15); frame_gerenciar.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame_gerenciar, text="Motoristas Cadastrados:").pack(anchor="w")
        self.lista_box = Listbox(frame_gerenciar, height=8, font=("Segoe UI", 10)); self.lista_box.pack(fill="x", pady=(5, 10)); self.lista_box.bind("<<ListboxSelect>>", self.on_select)
        ttk.Label(frame_gerenciar, text="Nome do Motorista:").pack(anchor="w"); self.nome_entry_var = tk.StringVar(); ttk.Entry(frame_gerenciar, textvariable=self.nome_entry_var).pack(fill="x", pady=(5, 20))
        frame_botoes = ttk.Frame(frame_gerenciar); frame_botoes.pack(fill="x"); frame_botoes.columnconfigure((0, 1), weight=1)
        ttk.Button(frame_botoes, text="Adicionar / Atualizar", command=self.save_driver, bootstyle="success").grid(row=0, column=0, padx=(0,5), sticky="ew")
        ttk.Button(frame_botoes, text="Remover Selecionado", command=self.remove_driver, bootstyle="danger-outline").grid(row=0, column=1, padx=(5,0), sticky="ew")
        self.populate_list()
    def populate_list(self):
        self.lista_box.delete(0, tk.END); [self.lista_box.insert(tk.END, name) for name in self.manifest_master.app_data["drivers"]]
    def on_select(self, evt):
        if self.lista_box.curselection(): self.nome_entry_var.set(self.lista_box.get(self.lista_box.curselection()[0]))
    def save_driver(self):
        new_name = self.nome_entry_var.get().strip()
        if not new_name: return
        if self.lista_box.curselection():
            old_name = self.lista_box.get(self.lista_box.curselection()[0])
            if old_name in self.manifest_master.app_data["drivers"]: self.manifest_master.app_data["drivers"].remove(old_name)
        if new_name not in self.manifest_master.app_data["drivers"]: self.manifest_master.app_data["drivers"].append(new_name)
        self.manifest_master.save_data(); self.populate_list(); self.manifest_master.update_driver_menu(); self.nome_entry_var.set(""); self.lista_box.selection_clear(0, tk.END)
    def remove_driver(self):
        if not self.lista_box.curselection(): return
        name = self.lista_box.get(self.lista_box.curselection()[0])
        if Messagebox.yesno(f"Deseja remover '{name}'?", "Confirmar", parent=self):
            if name in self.manifest_master.app_data["drivers"]: self.manifest_master.app_data["drivers"].remove(name)
            self.manifest_master.save_data(); self.populate_list(); self.manifest_master.update_driver_menu(); self.nome_entry_var.set("")

class ManageTemplatesWindow(Toplevel):
    def __init__(self, master, app_master):
        super().__init__(app_master)
        self.manifest_master = master; self.title("Gerenciar Textos Base"); self.geometry("550x500"); self.transient(app_master); self.grab_set()
        frame_textos = ttk.Frame(self, padding=15); frame_textos.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame_textos, text="Textos Cadastrados:").pack(anchor="w"); self.lista_box = Listbox(frame_textos, height=6, font=("Segoe UI", 10)); self.lista_box.pack(fill="x", pady=(5, 10)); self.lista_box.bind("<<ListboxSelect>>", self.on_select)
        ttk.Label(frame_textos, text="Nome do Texto (Ex: Aviso de Saída):").pack(anchor="w"); self.nome_template_var = tk.StringVar(); ttk.Entry(frame_textos, textvariable=self.nome_template_var).pack(fill="x", pady=(5, 10))
        ttk.Label(frame_textos, text="Conteúdo (use [NOME DO MOTORISTA] e [PLACA DO CARRO]):").pack(anchor="w"); self.conteudo_text = Text(frame_textos, height=8, wrap=tk.WORD, relief="sunken", borderwidth=1, padx=5, pady=5); self.conteudo_text.pack(fill="x", pady=(5, 20))
        frame_botoes = ttk.Frame(frame_textos); frame_botoes.pack(fill="x"); frame_botoes.columnconfigure((0, 1), weight=1)
        ttk.Button(frame_botoes, text="Adicionar / Atualizar Texto", command=self.save, bootstyle="success").grid(row=0, column=0, sticky="ew", padx=(0,5))
        ttk.Button(frame_botoes, text="Remover Texto Selecionado", command=self.remove, bootstyle="danger-outline").grid(row=0, column=1, sticky="ew", padx=(5,0))
        self.populate_list()
    def populate_list(self):
        self.lista_box.delete(0, tk.END); [self.lista_box.insert(tk.END, name) for name in sorted(self.manifest_master.app_data["templates"].keys())]
    def on_select(self, evt):
        if not self.lista_box.curselection(): return
        name = self.lista_box.get(self.lista_box.curselection()[0]); self.nome_template_var.set(name); self.conteudo_text.delete("1.0", tk.END); self.conteudo_text.insert("1.0", self.manifest_master.app_data["templates"].get(name, ""))
    def save(self):
        name = self.nome_template_var.get().strip(); content = self.conteudo_text.get("1.0", tk.END).strip()
        if not name or not content: Messagebox.show_warning("Nome e conteúdo não podem estar vazios.", "Entrada Inválida", parent=self); return
        if "[NOME DO MOTORISTA]" not in content or "[PLACA DO CARRO]" not in content and not Messagebox.askyesno("O texto não contém os marcadores. Deseja salvar mesmo assim?", "Aviso", parent=self): return
        self.manifest_master.app_data["templates"][name] = content; self.manifest_master.save_data(); self.populate_list(); self.manifest_master.update_template_menu(); self.nome_template_var.set(""); self.conteudo_text.delete("1.0", tk.END); self.lista_box.selection_clear(0, tk.END)
    def remove(self):
        if not self.lista_box.curselection() or len(self.manifest_master.app_data["templates"]) <= 1: return
        name = self.lista_box.get(self.lista_box.curselection()[0])
        if Messagebox.yesno(f"Deseja remover o texto '{name}'?", "Confirmar Remoção", parent=self):
            del self.manifest_master.app_data["templates"][name]; self.manifest_master.save_data(); self.populate_list(); self.manifest_master.update_template_menu(); self.nome_template_var.set(""); self.conteudo_text.delete("1.0", tk.END)

# ############################################################################
#
#   CLASSE PRINCIPAL DA APLICAÇÃO
#
# ############################################################################

class UnifiedApp(ttk.Window):
    def __init__(self):
        self.app_settings = self.load_app_settings()
        super().__init__(themename=self.app_settings.get("theme", "litera"))
        
        self.title("Sistema Unificado v3.0")
        self.geometry(self.app_settings.get("geometry", "1100x800"))
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        if icone_base64:
            try:
                self.icon_image = tk.PhotoImage(data=icone_base64)
                self.iconphoto(True, self.icon_image)
            except tk.TclError as e:
                logging.warning(f"Não foi possível carregar o ícone: {e}")
        
        self.current_frame = None
        self._create_main_layout()
        self._create_menu()
        self.show_frame(SernFrame)
        logging.info(f"Aplicação Unificada iniciada. Diretório de dados: {APP_DATA_DIR}")

    def load_app_settings(self):
        try:
            with open(APP_CONFIG_FILE, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"theme": "litera", "geometry": "1100x800"}

    def save_app_settings(self):
        self.app_settings['geometry'] = self.geometry()
        try:
            with open(APP_CONFIG_FILE, 'w') as f:
                json.dump(self.app_settings, f, indent=4)
        except Exception as e:
            logging.error(f"Não foi possível salvar as configurações da aplicação: {e}")

    def on_closing(self):
        self.save_app_settings()
        self.destroy()

    def _create_main_layout(self):
        self.grid_rowconfigure(0, weight=1); self.grid_columnconfigure(1, weight=1)
        nav_frame = ttk.Frame(self, padding=10, bootstyle="secondary"); nav_frame.grid(row=0, column=0, sticky="ns")
        ttk.Label(nav_frame, text="Ferramentas", font=("Segoe UI", 14, "bold"), bootstyle="inverse-secondary").pack(pady=10)
        self.sern_button = ttk.Button(nav_frame, text="Organizador de Notas", command=lambda: self.show_frame(SernFrame), bootstyle="primary", padding=10); self.sern_button.pack(fill="x", pady=5)
        self.manifest_button = ttk.Button(nav_frame, text="Gerador de Manifesto", command=lambda: self.show_frame(ManifestFrame), bootstyle="primary-outline", padding=10); self.manifest_button.pack(fill="x", pady=5)
        self.content_frame = ttk.Frame(self, padding=10); self.content_frame.grid(row=0, column=1, sticky="nsew"); self.content_frame.grid_rowconfigure(0, weight=1); self.content_frame.grid_columnconfigure(0, weight=1)
        self.frames = {F: F(self.content_frame) for F in (SernFrame, ManifestFrame)}
        for frame in self.frames.values(): frame.grid(row=0, column=0, sticky="nsew")

    def _create_menu(self):
        menubar = ttk.Menu(self); self.config(menu=menubar)
        self.file_menu = ttk.Menu(menubar, tearoff=False); menubar.add_cascade(label="Arquivo", menu=self.file_menu)
        self.config_menu = ttk.Menu(menubar, tearoff=False); menubar.add_cascade(label="Configurações", menu=self.config_menu)
        self.help_menu = ttk.Menu(menubar, tearoff=False); menubar.add_cascade(label="Ajuda", menu=self.help_menu)
        self._create_theme_menu()
        self.help_menu.add_command(label="Sobre...", command=self.show_about_window)

    def _create_theme_menu(self):
        theme_menu = ttk.Menu(self.config_menu, tearoff=False)
        self.config_menu.add_cascade(label="Temas", menu=theme_menu)
        self.selected_theme = tk.StringVar(value=self.app_settings.get("theme", "litera"))
        themes = ['litera', 'cosmo', 'flatly', 'journal', 'lumen', 'minty', 'pulse', 'sandstone', 'united', 'yeti', 'superhero', 'darkly', 'cyborg', 'vapor']
        for theme in themes:
            theme_menu.add_radiobutton(label=theme.capitalize(), variable=self.selected_theme, command=self.change_theme)
    
    def change_theme(self):
        self.app_settings['theme'] = self.selected_theme.get()
        self.save_app_settings()
        Messagebox.show_info("O tema foi alterado. Por favor, reinicie a aplicação para ver as mudanças.", "Tema Alterado", parent=self)

    def show_frame(self, frame_class):
        if self.current_frame == self.frames[frame_class]: return
        self.current_frame = self.frames[frame_class]
        self.current_frame.tkraise()
        self.update_menu_for_frame(frame_class)
        self.update_nav_buttons(frame_class)

    def update_nav_buttons(self, frame_class):
        self.sern_button.config(bootstyle="primary" if frame_class == SernFrame else "primary-outline")
        self.manifest_button.config(bootstyle="primary" if frame_class == ManifestFrame else "primary-outline")
            
    def update_menu_for_frame(self, frame_class):
        self.file_menu.delete(0, tk.END)
        self.config_menu.delete(0, self.config_menu.index('end')) # Limpa apenas as opções de config, mantém "Temas"
        
        if frame_class == SernFrame:
            sern_frame = self.frames[SernFrame]
            self.file_menu.add_command(label="Verificar/Atualizar Notas", command=sern_frame.scan_and_display_companies, accelerator="F5")
            self.file_menu.add_command(label="Limpar Todas as Pastas de Destino", command=sern_frame.clean_all_company_folders)
            self.bind("<F5>", lambda e: sern_frame.scan_and_display_companies())
            self.config_menu.add_command(label="Gerenciar Empresas...", command=sern_frame.open_config_window)
        else: self.unbind("<F5>")
        
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Fazer Backup das Configurações", command=self.backup_settings)
        self.file_menu.add_command(label="Restaurar Backup", command=self.restore_settings)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Sair", command=self.on_closing)

    def backup_settings(self):
        backup_path = filedialog.asksaveasfilename(title="Salvar Backup Como", defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if not backup_path: return
        all_settings = {
            'app_config': self.app_settings,
            'sern_config': self.frames[SernFrame].settings,
            'manifest_config': self.frames[ManifestFrame].app_data
        }
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(all_settings, f, indent=4, ensure_ascii=False)
            Messagebox.show_info("Backup realizado com sucesso!", "Sucesso", parent=self)
        except Exception as e:
            Messagebox.show_error(f"Não foi possível criar o backup:\n{e}", "Erro de Backup", parent=self)

    def restore_settings(self):
        if not Messagebox.yesno("Isso substituirá TODAS as configurações atuais e reiniciará o programa. Deseja continuar?", "Confirmar Restauração", parent=self): return
        restore_path = filedialog.askopenfilename(title="Abrir Arquivo de Backup", filetypes=[("JSON files", "*.json")])
        if not restore_path: return
        try:
            with open(restore_path, 'r', encoding='utf-8') as f: all_settings = json.load(f)
            if 'app_config' not in all_settings or 'sern_config' not in all_settings or 'manifest_config' not in all_settings:
                raise ValueError("Arquivo de backup inválido ou corrompido.")

            self.app_settings = all_settings['app_config']
            self.frames[SernFrame].settings = all_settings['sern_config']
            self.frames[ManifestFrame].app_data = all_settings['manifest_config']

            self.save_app_settings()
            self.frames[SernFrame].save_settings()
            self.frames[ManifestFrame].save_data()
            
            Messagebox.show_info("Configurações restauradas com sucesso! A aplicação será reiniciada.", "Sucesso", parent=self)
            self.on_closing()

        except Exception as e:
            Messagebox.show_error(f"Falha ao restaurar o backup:\n{e}", "Erro de Restauração", parent=self)

    def toggle_ui_state(self, enabled):
        state = "normal" if enabled else "disabled"
        for widget in self.winfo_children():
            if widget != self.content_frame:
                try:
                    if isinstance(widget, ttk.Frame) and widget == self.children['!frame']:
                         for btn in widget.winfo_children():
                             if isinstance(btn, ttk.Button): btn.config(state=state)
                except Exception: pass
        for menu_name in ["Arquivo", "Configurações", "Ajuda"]: self.children['!menu'].entryconfig(menu_name, state=state)

    def show_about_window(self):
        about_win = Toplevel(self); about_win.title("Sobre o Sistema Unificado"); about_win.geometry("450x300"); about_win.resizable(False, False); about_win.transient(self); about_win.grab_set()
        about_frame = ttk.Frame(about_win, padding=20); about_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(about_frame, text="Sistema Unificado", font=("Segoe UI", 16, "bold"), bootstyle="primary").pack(pady=5)
        ttk.Label(about_frame, text="Versão 3.0 (Usabilidade)", bootstyle="secondary").pack(pady=5)
        ttk.Label(about_frame, text="Uma ferramenta integrada para organização de notas fiscais\ne geração de manifestos de entrega.", justify="center").pack(pady=10)
        ttk.Separator(about_frame).pack(fill='x', pady=10)
        ttk.Label(about_frame, text="Desenvolvido por: Florest").pack()
        ttk.Button(about_frame, text="OK", bootstyle="primary", command=about_win.destroy).pack(pady=20)

if __name__ == "__main__":
    app = UnifiedApp()
    app.mainloop()