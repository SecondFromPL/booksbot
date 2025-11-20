import scrapy
from urllib.parse import urlparse, parse_qs, quote_plus
import logging # DODANO

class WebscrSpider(scrapy.Spider):
    name = 'webscr'
    allowed_domains = []
    
    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'DOWNLOAD_DELAY': 2,
        'COOKIES_ENABLED': False,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    }

    def start_requests(self):
        queries = [
            'Sklep internetowy Shoper.pl -site:shoper.pl',
            'Oprogramowanie Shoper -site:shoper.pl',
            'Powered by Shoper -site:shoper.pl'
        ]
        
        for query in queries:
            encoded_query = quote_plus(query)
            url = f'https://html.duckduckgo.com/lite/?q={encoded_query}&kl=pl-pl'
            logging.info(f"START: Rozpoczynam scraping dla zapytania: {query}") # LOGOWANIE
            yield scrapy.Request(url=url, callback=self.parse_duckduckgo_results)

    def parse_duckduckgo_results(self, response):
        
        # ZAPIS HTML: Zapisujemy kod HTML strony wyników do pliku
        filename = f'ddg_lite_results_{response.url.split("q=")[-1].split("&")[0]}.html'
        with open(filename, 'wb') as f:
            f.write(response.body)
        logging.info(f"ZAPISANO HTML: Strona wyników DuckDuckGo zapisana do {filename}") # LOGOWANIE
        
        # Parsowanie dla wersji LITE
        result_links = response.xpath("//a[starts-with(@href, 'http')]/@href").getall()
        
        logging.info(f"PARSOWANIE: Znaleziono {len(result_links)} potencjalnych linków na stronie wyników.") # LOGOWANIE

        for url in result_links:
            if 'duckduckgo' not in url:
                logging.info(f"LINK ZEWNĘTRZNY: Przechodzę do weryfikacji: {url}") # LOGOWANIE
                yield scrapy.Request(url=url, callback=self.verify_shoper, meta={'handle_httpstatus_list': [403, 404, 500]})

        # Paginacja dla wersji LITE
        next_page = response.xpath("//a[contains(text(), 'Next') or contains(text(), 'Następne')]/@href").get()
        
        if next_page:
            logging.info("PAGINACJA: Znaleziono link do następnej strony, kontynuuję.") # LOGOWANIE
            yield response.follow(next_page, callback=self.parse_duckduckgo_results)
            
    def verify_shoper(self, response):
        is_shoper = False
        
        generator = response.xpath('//meta[@name="generator"]/@content').get()
        if generator and 'shoper' in generator.lower():
            is_shoper = True
            
        if not is_shoper:
            footer_text = response.xpath('//footer//text()').getall()
            footer_content = " ".join(footer_text).lower()
            if 'shoper.pl' in footer_content or 'oprogramowanie shoper' in footer_content:
                is_shoper = True
        
        if not is_shoper:
            scripts = response.xpath('//script/@src').getall()
            for script in scripts:
                if 'shoper' in script.lower():
                    is_shoper = True
                    break

        if is_shoper:
            logging.info(f"!!! ZNALEZIONO SKLEP: {response.url}") # LOGOWANIE
            yield {
                'url': response.url,
                'title': response.css('title::text').get(),
                'generator': generator,
                'detected': True
            }
        
        logging.info(f"WERYFIKACJA: Zakończono sprawdzanie: {response.url}") # LOGOWANIE
