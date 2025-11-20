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
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        # Pozwól przechodzić dalej, nawet jeśli odpowiedź HTTP ma nietypowy/"błędny" status (np. 403/404/5xx/522)
        'HTTPERROR_ALLOW_ALL': True,
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
                # Akceptuj wszystkie statusy HTTP dla stron docelowych, aby nie przerywać crawl'a
                meta={'handle_httpstatus_all': True},
                # W przypadku błędów transportowych (timeout/DNS/reset) po prostu zaloguj i idź dalej
                errback=self.on_request_error,
            )

        # Paginacja dla wersji LITE
        next_page = response.xpath("//a[contains(text(), 'Next') or contains(text(), 'Następne')]/@href").get()

        if next_page:
            logging.info("PAGINACJA: Znaleziono link do następnej strony, kontynuuję.")
            yield response.follow(next_page, callback=self.parse_duckduckgo_results)
        else:
            # Fallback: DDG Lite czasem używa przycisku formularza "Next Page >" zamiast linku <a>
            try:
                form_request = scrapy.FormRequest.from_response(
                    response,
                    formxpath="//form[.//input[@type='submit' and contains(@class, 'navbutton') and (contains(@value, 'Next') or contains(@value, 'Następ'))]]",
                    clickdata={'type': 'submit', 'class': 'navbutton'},
                    callback=self.parse_duckduckgo_results,
                    errback=self.on_request_error,
                )
                logging.info("PAGINACJA: Brak linku <a>. Używam wysłania formularza (przycisk 'Next').")
                yield form_request
            except Exception as e:
                logging.info(
                    f"PAGINACJA: Nie znaleziono możliwości przejścia dalej (brak <a> i formularza). Szczegóły: {e}")

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
            # Detekcja 'tpay' na stronie głównej
            tpay_home = 'tpay' in (response.text or '').lower()

            # Spróbuj znaleźć link do strony o metodach płatności
            payment_href = self.find_payment_link(response)
            if payment_href:
                payment_url = response.urljoin(payment_href)
                logging.info(f"TPAY: Znaleziono potencjalną stronę płatności: {payment_url}. Sprawdzam 'tpay'.")
                # Przejdź do strony płatności i połącz wyniki (OR)
                yield scrapy.Request(
                    url=payment_url,
                    callback=self.check_payment_page_for_tpay,
                    meta={
                        'handle_httpstatus_all': True,
                        'tpay_found_home': tpay_home,
                        'shop_url': response.url,
                        'shop_title': response.css('title::text').get(),
                        'generator': generator,
                    },
                    errback=self.on_payment_error,
                )
            else:
                logging.info("TPAY: Nie znaleziono linku do strony płatności – używam wyniku ze strony głównej.")
                yield {
                    'url': response.url,
                    'title': response.css('title::text').get(),
                    'generator': generator,
                    'detected': True,
                    'tPay found': bool(tpay_home),
                }
        
        logging.info(f"WERYFIKACJA: Zakończono sprawdzanie: {response.url}")

    # --- Pomocnicze: wyszukiwanie linku do strony płatności ---
    def find_payment_link(self, response):
        """
        Szuka odnośnika prowadzącego do informacji o metodach płatności.
        Zwraca href (może być względny) lub None.
        """
        # Szukanie po atrybucie href – najczęstsze wzorce (z i bez polskich znaków)
        href_candidates = response.xpath(
            "//a["
            "contains(translate(@href,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'platnosc') or "
            "contains(translate(@href,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'platnosci') or "
            "contains(translate(@href,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'platnos') or "
            "contains(translate(@href,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'payments') or "
            "contains(translate(@href,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'payment') or "
            "contains(translate(@href,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'pay')"
            "]/@href"
        ).getall() or []

        # Szukanie po tekście linku (również ogólne sekcje jak „Płatność i dostawa”)
        text_candidates = response.xpath(
            "//a["
            "contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'metody płatności') or "
            "contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'formy płatności') or "
            "contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'sposoby płatności') or "
            "contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'płatno') or "
            "contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'platno') or "
            "contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'płatność i dostawa') or "
            "contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'platnosc i dostawa')"
            "]/@href"
        ).getall() or []

        # Połącz i zuniikuj, zachowując kolejność
        seen = set()
        for href in href_candidates + text_candidates:
            if not href:
                continue
            if href.startswith('#'):
                continue
            if href not in seen:
                seen.add(href)
                return href
        return None

    def check_payment_page_for_tpay(self, response):
        """Callback: sprawdza występowanie 'tpay' na stronie metod płatności i zwraca item."""
        tpay_home = bool(response.meta.get('tpay_found_home', False))
        tpay_payment = 'tpay' in (response.text or '').lower()
        combined = tpay_home or tpay_payment

        logging.info(
            f"TPAY: Wynik: home={tpay_home}, payment={tpay_payment}, combined={combined} | {response.url}"
        )

        yield {
            'url': response.meta.get('shop_url', response.url),
            'title': response.meta.get('shop_title'),
            'generator': response.meta.get('generator'),
            'detected': True,
            'tPay found': bool(combined),
        }

    def on_payment_error(self, failure):
        """
        Specjalny errback dla strony płatności – na błąd i tak zwróć item
        z wartością opartą o stronę główną.
        """
        try:
            req = getattr(failure, 'request', None)
            meta = req.meta if req is not None else {}
            url = req.url if req is not None else 'UNKNOWN_URL'
        except Exception:
            meta = {}
            url = 'UNKNOWN_URL'

        logging.warning(
            f"BŁĄD POBIERANIA STRONY PŁATNOŚCI: {failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else failure} | URL: {url}. Zwracam item z wynikiem z homepage."
        )

        yield {
            'url': meta.get('shop_url', url),
            'title': meta.get('shop_title'),
            'generator': meta.get('generator'),
            'detected': True,
            'tPay found': bool(meta.get('tpay_found_home', False)),
        }

    def on_request_error(self, failure):
        """
        Errback dla błędów pobierania (timeout, DNS, ConnectionRefused, itp.).
        Zamiast przerywać działanie, logujemy i kontynuujemy crawl.
        """
        try:
            req = getattr(failure, 'request', None)
            url = req.url if req is not None else 'UNKNOWN_URL'
        except Exception:
            url = 'UNKNOWN_URL'

        logging.warning(
            f"BŁĄD POBIERANIA: {failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else failure} | URL: {url}. Kontynuuję.")
        # Brak raise/return itemów – po prostu kontynuujemy bez tej strony
