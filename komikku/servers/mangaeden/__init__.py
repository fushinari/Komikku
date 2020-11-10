# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import json
from collections import OrderedDict
from bs4 import BeautifulSoup
import requests

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

SERVER_NAME = 'Manga Eden'

headers = OrderedDict(
    [
        ('User-Agent', USER_AGENT),
        ('Accept-Language', 'en-US,en;q=0.5'),
    ]
)


class Mangaeden(Server):
    id = 'mangaeden'
    name = SERVER_NAME
    lang = 'en'

    base_url = 'https://www.mangaeden.com'
    search_url = base_url + '/en/en-directory/'
    most_populars_url = search_url + '?order=1'
    manga_url = base_url + '/en/en-manga/{0}/'
    chapter_url = base_url + '/en/en-manga/{0}/{1}/1/'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = headers

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

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

        data['name'] = soup.find('span', class_='manga-title').text.strip()

        cover_element = soup.find('div', class_='mangaImage2')
        if cover_element:
            data['cover'] = 'https:{0}'.format(cover_element.img.get('src'))

        # Details
        for element in soup.find_all('div', class_='rightBox')[1].find_all():
            if element.name == 'h4':
                label = element.text.strip()

                if label.startswith(('Status', 'Stato')):
                    status = element.find_all_next(string=True, limit=2)[1].strip().lower()

                    if status in ('ongoing', 'in corso'):
                        data['status'] = 'ongoing'
                    elif status in ('completed', 'completato'):
                        data['status'] = 'complete'
                    elif status in ('suspended', 'sospeso'):
                        data['status'] = 'suspended'

                continue

            if element.name == 'a':
                if label.startswith(('Author', 'Autore', 'Artist', 'Artista')):
                    data['authors'].append(element.text.strip())
                elif label.startswith(('Genres', 'Genere')):
                    data['genres'].append(element.text.strip())

        # Synopsis
        synopsis_element = soup.find('h2', id='mangaDescription')
        if synopsis_element:
            data['synopsis'] = synopsis_element.text.strip()

        # Chapters
        elements = soup.find('table').tbody.find_all('tr')
        for element in reversed(elements):
            tds_elements = element.find_all('td')

            data['chapters'].append(dict(
                slug=tds_elements[0].a.get('href').split('/')[-3],
                title=tds_elements[0].b.text.strip(),
                date=convert_date_string(tds_elements[3].text.strip(), format='%b %d, %Y'),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        data = dict(
            pages=[],
        )
        for script_element in soup.find_all('script'):
            script = script_element.string
            if not script or not script.strip().startswith('var pages'):
                continue

            pages = json.loads(script.strip().split('\n')[0].split('=')[1][:-1])
            for page in pages:
                data['pages'].append(dict(
                    slug=None,  # not necessary, we know image url already
                    image='https:{0}'.format(page['fs']),
                ))
            break

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(page['image'], headers=dict(referer=self.chapter_url.format(manga_slug, chapter_slug)))
        if r is None or r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['image'].split('/')[-1],
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
        for tr_element in soup.find('table', id='mangaList').tbody.find_all('tr'):
            td_elements = tr_element.find_all('td')
            a_element = td_elements[0].a
            results.append(dict(
                slug=a_element.get('href').split('/')[-2],
                name=a_element.text.strip(),
            ))

        return results

    def search(self, term):
        r = self.session_get(self.search_url, params=dict(title=term))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        results = []
        for tr_element in soup.find('table', id='mangaList').tbody.find_all('tr'):
            td_elements = tr_element.find_all('td')

            if td_elements[3].text.strip() == '0':
                # Skipped manga with no chapters
                continue

            a_element = td_elements[0].a
            results.append(dict(
                slug=a_element.get('href').split('/')[-2],
                name=a_element.text.strip(),
            ))

        return results


class Mangaeden_it(Mangaeden):
    id = 'mangaeden_it'
    name = SERVER_NAME
    lang = 'it'

    base_url = 'http://www.mangaeden.com'
    search_url = base_url + '/it/it-directory/'
    most_populars_url = search_url + '?order=1'
    manga_url = base_url + '/it/it-manga/{0}/'
    chapter_url = base_url + '/it/it-manga/{0}/{1}/1/'
