import logging
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import scrapy


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
            logging.info(f"START: Rozpoczynam scraping dla zapytania: {query}")
            yield scrapy.Request(url=url, callback=self.parse_duckduckgo_results)

    def parse_duckduckgo_results(self, response):

        # ZAPIS HTML DLA ZYTE CLOUD (bezpieczny, nie powoduje błędów gdy 'job' nie istnieje)
        filename = f'ddg_lite_results_{response.url.split("q=")[-1].split("&")[0]}.html'

        job = response.meta.get('job')
        if job and hasattr(job, 'save_content'):
            try:
                job.save_content(response.body, filename)
                logging.info(
                    f"ZAPISANO HTML: Strona wyników DuckDuckGo zapisana jako {filename} w Job's Files.")
            except Exception as e:
                # W środowisku lokalnym lub gdy API jest niedostępne – ignoruj błąd i przejdź dalej
                logging.warning(
                    f"NIE UDAŁO SIĘ ZAPISAĆ DO JOB FILES: {e}. Kontynuuję bez zapisu w Zyte.")
        else:
            # Fallback do lokalnego systemu plików (może być ignorowany w środowisku Zyte)
            try:
                with open(filename, 'wb') as f:
                    f.write(response.body)
                logging.info(
                    f"ZAPISANO HTML LOKALNIE: Strona wyników zapisana do {filename}")
            except Exception as e:
                logging.warning(
                    f"NIE UDAŁO SIĘ ZAPISAĆ LOKALNIE: {e}. Kontynuuję bez zapisu pliku.")
        # Parsowanie linków wyników (DuckDuckGo Lite używa przekierowań /l/?uddg=...)
        raw_links = response.xpath(
            "//a[contains(@class, 'result-link')]/@href | "
            "//a[contains(@href, '/l/?uddg=')]/@href | "
            "//a[starts-with(@href, 'http')]/@href"
        ).getall()

        unique_targets = []
        seen = set()

        for href in raw_links:
            if not href:
                continue
            # Uzupełnij schemat dla linków zaczynających się od '//'
            if href.startswith('//'):
                href = 'https:' + href

            # Pomijamy nie-HTTP(S)
            if not (href.startswith('http://') or href.startswith('https://')):
                continue

            parsed = urlparse(href)

            # Linki DDG typu /l/?uddg=... – wyciągamy link docelowy
            if parsed.netloc.endswith('duckduckgo.com') and parsed.path.startswith('/l'):
                qs = parse_qs(parsed.query)
                target = qs.get('uddg', [None])[0]
                if not target:
                    continue
                target = unquote(target)
                if target.startswith('//'):
                    target = 'https:' + target
                if not (target.startswith('http://') or target.startswith('https://')):
                    continue
                final_url = target
            else:
                # Pomijamy inne wewnętrzne linki DDG
                if 'duckduckgo.com' in parsed.netloc:
                    continue
                final_url = href

            if final_url not in seen:
                seen.add(final_url)
                unique_targets.append(final_url)

        logging.info(
            f"PARSOWANIE: Surowe linki={len(raw_links)}, unikalne cele={len(unique_targets)}."
        )

        for url in unique_targets:
            logging.info(f"LINK ZEWNĘTRZNY: Przechodzę do weryfikacji: {url}")
            yield scrapy.Request(
                url=url,
                callback=self.verify_shoper,
                meta={'handle_httpstatus_list': [403, 404, 500]}
            )

        # Paginacja dla wersji LITE
        next_page = response.xpath("//a[contains(text(), 'Next') or contains(text(), 'Następne')]/@href").get()

        if next_page:
            logging.info("PAGINACJA: Znaleziono link do następnej strony, kontynuuję.")
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
            logging.info(f"!!! ZNALEZIONO SKLEP: {response.url}")
            yield {
                'url': response.url,
                'title': response.css('title::text').get(),
                'generator': generator,
                'detected': True
            }
        
        logging.info(f"WERYFIKACJA: Zakończono sprawdzanie: {response.url}")