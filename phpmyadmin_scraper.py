import requests
from bs4 import BeautifulSoup
import re
import sys
import os
from datetime import datetime
from dotenv import load_dotenv


class SimplePhpMyAdminScraper:
    def __init__(self, url, username, password):
        """Инициализация скрапера."""
        self.base_url = url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        })

    def login(self):
        """Авторизация в phpMyAdmin."""
        try:
            print("🔐 Подключение к phpMyAdmin...")
            
            login_url = f"{self.base_url}/index.php"
            response = self.session.get(login_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')

            token = None
            token_input = soup.find('input', {'name': 'token'})
            if token_input:
                token = token_input.get('value')
                print("🔑 CSRF токен найден")

            login_data = {
                'pma_username': self.username,
                'pma_password': self.password,
                'server': '1',
                'lang': 'ru',
            }
            
            if token:
                login_data['token'] = token

            response = self.session.post(login_url, data=login_data)
            response.raise_for_status()

            if 'logout' in response.text.lower() or 'выход' in response.text.lower():
                print("✅ Авторизация успешна!")
                return True
            else:
                print("❌ Ошибка авторизации")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка подключения: {e}")
            return False

    def get_data(self, database, table):
        """Получение данных из таблицы."""
        try:
            print(f"📊 Извлечение данных из {database}.{table}...")
            
            urls = [
                f"{self.base_url}/index.php?route=/table/browse&db={database}&table={table}",
                f"{self.base_url}/index.php?db={database}&table={table}&target=browse", 
                f"{self.base_url}/index.php?route=/sql&db={database}&table={table}",
                f"{self.base_url}/index.php?db={database}&table={table}",
            ]
            
            for url in urls:
                try:
                    response = self.session.get(url)
                    
                    if response.status_code == 200:
                        data = self.parse_page(response.text, table)
                        if data:
                            return data
                        
                except Exception as e:
                    continue

            return self.try_sql_query(database, table)
            
        except Exception as e:
            print(f"❌ Ошибка получения данных: {e}")
            return None

    def try_sql_query(self, database, table):
        """Попытка выполнить SQL запрос."""
        try:
            sql_url = f"{self.base_url}/index.php?route=/sql&db={database}"
            sql_query = f"SELECT * FROM `{table}` LIMIT 20"
            
            # POST запрос с SQL
            data = {
                'sql_query': sql_query,
                'submit': 'Go'
            }
            
            response = self.session.post(sql_url, data=data)
            
            if response.status_code == 200:
                return self.parse_page(response.text, table)
            
            return None
            
        except Exception as e:
            print(f"❌ Ошибка SQL запроса: {e}")
            return None

    def parse_page(self, html, table_name):
        """Парсинг HTML страницы для извлечения данных."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            data_table = None
 
            priority_selectors = [
                'table.table_results',
                'table[class*="data"]',
                'table[id*="table"]',
                'table[class*="result"]',
            ]
            
            for selector in priority_selectors:
                data_table = soup.select_one(selector)
                if data_table:
                    break
            if not data_table:
                tables = soup.find_all('table')
                for table in tables:
                    table_text = table.get_text()

                    if ('`' in table_text and '=' in table_text) or any(word in table_text.lower() for word in ['id', 'name', 'user', 'email']):
                        data_table = table
                        break
            
            if not data_table:
                tables = soup.find_all('table')
                if tables:
                    data_table = max(tables, key=lambda t: len(t.find_all('tr')))
            
            if not data_table:
                return None

            rows = data_table.find_all('tr')
            if len(rows) < 2:
                return None
            
            headers = []
            data_rows = []
            
            for row_idx, row in enumerate(rows):
                cells = row.find_all(['td', 'th'])
                if not cells:
                    continue
                
                row_data = []
                for cell_idx, cell in enumerate(cells):
                    if cell.find('input', type='checkbox') or cell.find('button'):
                        continue
                    
                    full_text = cell.get_text(strip=True)
                    
                    if '=' in full_text and '`' in full_text:
                        lines = full_text.split('\n')
                        values = []
                        
                        for line in lines:
                            line = line.strip()
                            if '=' in line and '`' in line:
                                match = re.search(r'=\s*(.+)', line)
                                if match:
                                    value = match.group(1).strip().strip('`\'"')
                                    if value and value not in values:
                                        values.append(value)
                        
                        if values:
                            final_value = values[0] if len(values) == 1 else ' '.join(values)
                            row_data.append(final_value)
                    else:
                        excluded = ['Изменить', 'Копировать', 'Удалить', 'Edit', 'Copy', 'Delete', '', '✓', '×']
                        
                        if (full_text and 
                            full_text not in excluded and 
                            len(full_text) < 100 and
                            not any(word in full_text.lower() for word in ['панель', 'навигация', 'настройки'])):
                            row_data.append(full_text)
                
                if row_data:
                    is_config_row = any(len(cell) > 100 or 'панель' in cell.lower() or 'навигация' in cell.lower() 
                                       for cell in row_data)
                    
                    if not is_config_row:
                        if row_idx == 0 or (not headers and len(row_data) <= 5):
                            headers = row_data
                        else:

                            if len(row_data) > len(headers) * 2:

                                records = []
                                i = 0
                                while i < len(row_data):

                                    if i + 1 < len(row_data):
                                        id_val = row_data[i]
                                        name_val = row_data[i + 1]
                                        
        
                                        if id_val.isdigit() and not name_val.isdigit():
                                            records.append([id_val, name_val])
                                            i += 2
                                        else:
                                            i += 1
                                    else:
                                        i += 1

                                for record in records:
                                    data_rows.append(record)
                            else:
                                if len(row_data) > len(headers):
                                    
                                    if len(row_data) == 3 and len(headers) == 2:
                                        final_row = [row_data[1], row_data[2]]  
                                        data_rows.append(final_row)
                                    else:
                                        final_row = row_data[:len(headers)]
                                        data_rows.append(final_row)
                                else:
                                    data_rows.append(row_data)
            
            if data_rows and len(data_rows) > 0:
                first_row = ' '.join(str(cell) for cell in data_rows[0])
                if len(first_row) > 200 or any(word in first_row.lower() for word in ['панель', 'навигация', 'логотип', 'настройки']):
                    return None
                return {
                    'headers': headers if headers else [f'Столбец_{i+1}' for i in range(len(data_rows[0]))],
                    'rows': data_rows,
                    'table': table_name
                }
            
            return None
            
        except Exception as e:
            print(f"❌ Ошибка парсинга: {e}")
            return None

    def print_results(self, data):
        """Красивый вывод результатов."""
        if not data:
            print("❌ Нет данных для вывода")
            return
        
        headers = data['headers']
        rows = data['rows']
        table_name = data['table']
        
        col_widths = []
        for i, header in enumerate(headers):
            width = len(str(header))
            for row in rows:
                if i < len(row):
                    width = max(width, len(str(row[i])))
            col_widths.append(min(max(width, 8), 40))  
        
        print("\n" + "="*80)
        print(f"📊 ДАННЫЕ ИЗ ТАБЛИЦЫ: {table_name}")
        print(f"📈 Найдено записей: {len(rows)}")
        print(f"⏰ Время: {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}")
        print("="*80)
        
        header_line = " | ".join(headers[i].ljust(col_widths[i]) for i in range(len(headers)))
        print(header_line)
        print("-" * len(header_line))
        
        for row in rows:
            while len(row) < len(headers):
                row.append('')
            
            row_line = " | ".join(str(row[i]).ljust(col_widths[i]) for i in range(len(headers)))
            print(row_line)
        
        print("="*80)
        print(f"📊 Столбцов: {len(headers)} | Строк: {len(rows)}")


def main():
    """Основная функция."""
    
    # Загружаем конфигурацию из .env файла
    load_dotenv()
    
    URL = os.getenv('PHPMYADMIN_URL')
    USERNAME = os.getenv('PHPMYADMIN_USERNAME')
    PASSWORD = os.getenv('PHPMYADMIN_PASSWORD')
    DATABASE = os.getenv('DATABASE_NAME')
    TABLE = os.getenv('TABLE_NAME')
    
    # Проверяем, что все переменные загружены
    if not all([URL, USERNAME, PASSWORD, DATABASE, TABLE]):
        print("❌ Ошибка: Не все переменные окружения заданы в .env файле")
        print("Требуются: PHPMYADMIN_URL, PHPMYADMIN_USERNAME, PHPMYADMIN_PASSWORD, DATABASE_NAME, TABLE_NAME")
        sys.exit(1)
    
    print("🌐 ИЗВЛЕКАТЕЛЬ ДАННЫХ PHPMYADMIN")
    print("="*50)
    print(f"🎯 Сервер: {URL}")
    print(f"🗄️  База: {DATABASE}")
    print(f"📋 Таблица: {TABLE}")
    print("="*50)
    
    scraper = SimplePhpMyAdminScraper(URL, USERNAME, PASSWORD)
    
    try:
        # Авторизация
        if not scraper.login():
            print("❌ Не удалось авторизоваться")
            sys.exit(1)
        
        # Получение данных
        data = scraper.get_data(DATABASE, TABLE)
        
        if data:
            scraper.print_results(data)
            print("\n🎉 Готово!")
        else:
            print("❌ Данные не найдены")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 