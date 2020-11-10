# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import cloudscraper

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server

SERVER_NAME = 'ScanOnePiece'


class Scanonepiece(Server):
    id = 'scanonepiece'
    name = SERVER_NAME
    lang = 'fr'

    base_url = 'https://www.scan-vf.net'
    search_url = base_url + '/search'
    most_populars_url = base_url + '/filterList?page=1&sortBy=views&asc=false'
    manga_url = base_url + '/{0}'
    chapter_url = base_url + '/{0}/{1}'
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

        data['name'] = soup.find_all('h2', class_='widget-title')[0].text.strip()
        data['cover'] = self.cover_url.format(data['slug'])

        # Details
        elements = soup.find('dl', class_='dl-horizontal').findChildren(recursive=False)
        for element in elements:
            if element.name not in ('dt', 'dd'):
                continue

            if element.name == 'dt':
                label = element.text
                continue

            if label.startswith('Auteur') or label.startswith('Artist'):
                value = element.text.strip()
                for t in value.split(','):
                    t = t.strip()
                    if t not in data['authors']:
                        data['authors'].append(t)
            elif label.startswith('Catégories'):
                data['genres'] = [a_element.text.strip() for a_element in element.find_all('a')]
            elif label.startswith('Statut'):
                value = element.text.strip().lower()
                if value == 'en cours':
                    data['status'] = 'ongoing'
                elif value == 'terminé':
                    data['status'] = 'complete'

        data['synopsis'] = soup.find('div', class_='well').p.text.strip()
        alert_element = soup.find('div', class_='alert-danger')
        if alert_element:
            data['synopsis'] += '\n\n' + alert_element.text.strip()

        # Chapters
        elements = soup.find('ul', class_='chapters').find_all('li', recursive=False)
        for element in reversed(elements):
            h5 = element.h5
            if not h5:
                continue

            slug = h5.a.get('href').split('/')[-1]
            title = '{0}: {1}'.format(h5.a.text.strip(), h5.em.text.strip())
            date = element.div.div

            data['chapters'].append(dict(
                slug=slug,
                date=convert_date_string(date.text.strip(), format='%d %b. %Y'),
                title=title
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
        """ Returns list of most viewed manga """
        r = self.session_get(self.most_populars_url)
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/plain':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        results = []
        for a_element in soup.find_all('a', class_='chart-title'):
            results.append(dict(
                name=a_element.text.strip(),
                slug=a_element.get('href').split('/')[-1],
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
