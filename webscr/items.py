import scrapy

class WebscrItem(scrapy.Item):
    url = scrapy.Field()
    title = scrapy.Field()
    generator = scrapy.Field()
    detected = scrapy.Field()
