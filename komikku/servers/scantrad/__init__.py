# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import requests
import unidecode

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

SERVER_NAME = 'Scantrad France'


class Scantrad(Server):
    id = 'scantrad'
    name = SERVER_NAME
    lang = 'fr'

    base_url = 'https://scantrad.net'
    search_url = base_url + '/mangas'
    manga_url = base_url + '/{0}'
    chapter_url = base_url + '/mangas/{0}/{1}'
    image_url = base_url + '/{0}'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

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

        soup = BeautifulSoup(r.text, 'html.parser')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[SERVER_NAME, ],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        div_info = soup.find('div', class_='mf-info')
        data['name'] = div_info.find('div', class_='titre').text.strip()
        data['cover'] = '{0}/{1}'.format(self.base_url, div_info.find('div', class_='poster').img.get('src'))

        status = div_info.find_all('div', class_='sub-i')[-1].span.text.strip().lower()
        if status == 'en cours':
            data['status'] = 'ongoing'
        elif status == 'terminé':
            data['status'] = 'complete'

        data['synopsis'] = div_info.find('div', class_='synopsis').text.strip()

        # Chapters
        for div_element in reversed(soup.find('div', id='chap-top').find_all('div', class_='chapitre')):
            btns_elements = div_element.find('div', class_='ch-right').find_all('a')
            if len(btns_elements) < 2:
                continue

            data['chapters'].append(dict(
                slug=btns_elements[0].get('href').split('/')[-1],
                date=convert_date_string(div_element.find('div', class_='chl-date').text),
                title='{0} {1}'.format(
                    div_element.find('span', class_='chl-num').text.strip(),
                    div_element.find('span', class_='chl-titre').text.strip()
                ),
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

        if r.url[:-1] == self.base_url:
            # Chapter page doesn't exist, we have been redirected to homepage
            return None
        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        imgs_elements = soup.find('div', class_='main_img').find_all('img')

        data = dict(
            pages=[],
        )
        for img_element in imgs_elements:
            url = img_element.get('data-src')
            if not url or not url.startswith('lel'):
                continue

            data['pages'].append(dict(
                slug=None,
                image=url,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(self.image_url.format(page['image']))
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
        return self.search()

    def search(self, term=None):
        r = self.session_get(self.search_url)
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        results = []
        for a_element in soup.find('div', class_='h-left').find_all('a'):
            name = a_element.find('div', class_='hmi-titre').text.strip()

            if term is None or unidecode.unidecode(term).lower() in unidecode.unidecode(name).lower():
                results.append(dict(
                    slug=a_element.get('href').split('/')[-1],
                    name=name,
                ))

        return results
