import scrapy
from urllib.parse import urlparse, parse_qs, quote_plus

class WebscrSpider(scrapy.Spider):
    name = 'webscr'
    allowed_domains = []
    
   custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'DOWNLOAD_DELAY': 2,
        'COOKIES_ENABLED': False,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    }

    from urllib.parse import urlparse, parse_qs, quote_plus
# upewnij się, że masz import quote_plus na górze pliku!

# ...

    def start_requests(self):
        queries = [
            'site:.pl "Sklep internetowy Shoper"',
            'site:.pl "Oprogramowanie Shoper"',
            'site:.pl "Powered by Shoper"'
        ]
        
        for query in queries:
            encoded_query = quote_plus(query)
            # Używamy formatu html DDG
            url = f'https://html.duckduckgo.com/html/?q={encoded_query}'
            # Wracamy do prostego requestu bez zaawansowanych nagłówków JS
            yield scrapy.Request(url=url, callback=self.parse_duckduckgo_results)


def parse_duckduckgo_results(self, response):
        
        # Selekcja linków wyników (klasa result__url w DDG-H)
        result_links = response.css('.result__url::attr(href)').getall()
        
        for url in result_links:
            # DDG-H zwraca bezpośrednie URL, nie wymaga dekodowania /url?q=
            if url.startswith('http') and 'duckduckgo' not in url:
                yield scrapy.Request(url=url, callback=self.verify_shoper, meta={'handle_httpstatus_list': [403, 404, 500]})

        # Selekcja linku do następnej strony 
        next_page = response.xpath("//div[@id='content_bottom']//a[contains(text(), 'Next')]/@href").get()
        
        if next_page:
            # DuckDuckGo HTML pagination jest relatywna
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
            yield {
                'url': response.url,
                'title': response.css('title::text').get(),
                'generator': generator,
                'detected': True
            }
