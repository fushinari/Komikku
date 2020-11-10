# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import cloudscraper

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server

SERVER_NAME = 'Submanga'


class Submanga(Server):
    id = 'submanga'
    name = SERVER_NAME
    lang = 'es'

    base_url = 'https://submangas.net'
    search_url = base_url + '/search'
    most_populars_url = base_url + '/filterList?page=1&sortBy=views&asc=false'
    manga_url = base_url + '/manga/{0}'
    chapter_url = base_url + '/manga/{0}/{1}'
    image_url = base_url + '/uploads/manga/{0}/chapters/{1}/{2}'
    cover_url = base_url + '/uploads/manga/{0}/cover/cover_250x350.jpg'

    def __init__(self):
        if self.session is None:
            self.session = cloudscraper.create_scraper()

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        name_element = soup.find_all('h3')[0]
        name_element.i.decompose()
        name_element.small.decompose()
        data['name'] = name_element.text.strip()
        data['cover'] = self.cover_url.format(data['slug'])

        # Details
        elements = soup.find('div', class_='list-group').find_all('span', class_='list-group-item')
        for element in elements:
            label = element.b.text.strip()

            if label.startswith(('Autor', 'Artist')):
                for a_element in element.find_all('a'):
                    value = a_element.text.strip()
                    if value not in data['authors']:
                        data['authors'].append(value)
            elif label.startswith('Categorías'):
                for a_element in element.find_all('a'):
                    value = a_element.text.strip()
                    if value not in data['authors']:
                        data['genres'].append(value)
            elif label.startswith('Estado'):
                value = element.span.text.strip().lower()
                if value in ('complete', 'ongoing'):
                    data['status'] = value
            elif label.startswith('Resumen'):
                element.b.extract()
                data['synopsis'] = element.text.strip()

        # Chapters
        elements = soup.find('div', class_='capitulos-list').find_all('tr')
        for element in reversed(elements):
            td_elements = element.find_all('td')
            a_element = td_elements[0].find('a')
            date_element = td_elements[1]
            date_element.i.extract()
            date_element.span.extract()

            data['chapters'].append(dict(
                slug=a_element.get('href').split('/')[-1],
                title=a_element.text.strip(),
                date=convert_date_string(date_element.text.strip(), '%d %b. %Y'),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages (list of images filenames) are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        pages_imgs = soup.find('div', id='all').find_all('img')

        data = dict(
            pages=[],
        )
        for img in pages_imgs:
            data['pages'].append(dict(
                slug=None,  # not necessary, we know image url directly
                image=img.get('data-src').strip().split('/')[-1],
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(self.image_url.format(manga_slug, chapter_slug, page['image']))
        if r is None or r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['image'],
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url.format(slug)

    def get_most_populars(self):
        """ Returns most viewed manga list """
        r = self.session_get(self.most_populars_url)
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        results = []
        for element in soup.find_all('div', class_='thumbnail'):
            results.append(dict(
                name=element.find('h3').a.text.strip(),
                slug=element.a.get('href').split('/')[-1],
            ))

        return results

    def search(self, term):
        self.session_get(self.base_url)
        r = self.session_get(self.search_url, params=dict(query=term))
        if r is None:
            return None

        if r.status_code == 200:
            try:
                # Returned data for each manga:
                # value: name of the manga
                # data: slug of the manga
                data = r.json()['suggestions']

                results = []
                for item in data:
                    results.append(dict(
                        slug=item['data'],
                        name=item['value'],
                    ))

                return results
            except Exception:
                return None

        return None
