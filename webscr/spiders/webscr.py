import scrapy
from urllib.parse import urlparse, parse_qs

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
            'site:.pl "Sklep internetowy Shoper"',
            'site:.pl "Oprogramowanie Shoper"',
            'site:.pl "Powered by Shoper"'
        ]
        
        for query in queries:
            url = f'https://www.google.com/search?q={query}'
            yield scrapy.Request(url=url, callback=self.parse_google_results)

    def parse_google_results(self, response):
        result_links = response.xpath('//div[@class="g"]//a/@href').getall()
        
        if not result_links:
            result_links = response.xpath('//div[contains(@class, "yuRUbf")]/a/@href').getall()
            
        for link in result_links:
            url = link
            
            if '/url?q=' in link:
                parsed = parse_qs(urlparse(link).query)
                if 'q' in parsed:
                    url = parsed['q'][0]
            
            if url.startswith('http') and 'google' not in url:
                yield scrapy.Request(url=url, callback=self.verify_shoper, meta={'handle_httpstatus_list': [403, 404, 500]})

        next_page = response.css('a#pnnext::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self.parse_google_results)
            
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
