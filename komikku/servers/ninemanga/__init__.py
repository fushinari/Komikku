# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from collections import OrderedDict
from bs4 import BeautifulSoup
import requests
from urllib.parse import unquote_plus

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

SERVER_NAME = 'Nine Manga'

headers = OrderedDict(
    [
        ('User-Agent', USER_AGENT),
        ('Accept-Language', 'en-US,en;q=0.5'),
    ]
)


class Ninemanga(Server):
    id = 'ninemanga'
    name = SERVER_NAME
    lang = 'en'

    base_url = 'http://www.ninemanga.com'
    search_url = base_url + '/search/ajax/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}'
    page_url = chapter_url

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

        if r.url == self.base_url:
            # Manga page doesn't exist, we have been redirected to homepage
            return None
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

        name = soup.find('div', class_='ttline').h1.text.strip()
        name = name.replace(' Manga', '').replace(' Манга', '')  # cleaning
        data['name'] = name
        data['cover'] = soup.find('a', class_='bookface').img.get('src')

        # Details
        elements = soup.find('ul', class_='message').find_all('li')
        for element in elements:
            label = element.b.text

            if label.startswith(('Author', 'Auteur', 'Autor')):
                data['authors'] = [element.a.text.strip(), ]
            elif label.startswith(('Genre', 'Genre', 'Género', 'Genere', 'Gênero')):
                for a_element in element.find_all('a'):
                    data['genres'].append(a_element.text)
            elif label.startswith(('Status', 'Statut', 'Estado', 'Stato')):
                value = element.find_all('a')[0].text.strip().lower()

                if value in ('ongoing', 'en cours', 'laufende', 'en curso', 'in corso', 'em tradução'):
                    data['status'] = 'ongoing'
                elif value in ('complete', 'complété', 'abgeschlossen', 'completado', 'completato', 'completo'):
                    data['status'] = 'complete'

        # Synopsis
        synopsis_element = soup.find('p', itemprop='description')
        if synopsis_element:
            synopsis_element.b.extract()
            data['synopsis'] = synopsis_element.text.strip()

        # Chapters
        div_element = soup.find('div', class_='chapterbox')
        if div_element:
            li_elements = div_element.find_all('li')
            for li_element in reversed(li_elements):
                slug = li_element.a.get('href').split('/')[-1].replace('.html', '')
                data['chapters'].append(dict(
                    slug=slug,
                    title=li_element.a.text.strip(),
                    date=convert_date_string(li_element.span.text.strip(), format='%b %d, %Y'),
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
        options_elements = soup.find('select', id='page').find_all('option')

        data = dict(
            pages=[],
        )
        for option_element in options_elements:
            data['pages'].append(dict(
                slug=option_element.get('value').split('/')[-1],
                image=None,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        # Scrap HTML page to get image url
        r = self.session_get(self.page_url.format(manga_slug, page['slug']))
        if r is None:
            return None

        soup = BeautifulSoup(r.text, 'html.parser')
        url = soup.find('img', id='manga_pic_1').get('src')

        # Get scan image
        r = self.session_get(url)
        if r is None or r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=url.split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url.format(slug)

    def get_most_populars(self):
        """ Returns Hot manga list """
        r = self.session_get(self.most_populars_url)
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        results = []
        for a_element in soup.find('ul', class_='direlist').find_all('a', class_='bookname'):
            results.append(dict(
                name=a_element.text.strip(),
                slug=unquote_plus(a_element.get('href')).split('/')[-1][:-5],
            ))

        return results

    def search(self, term):
        r = self.session_get(self.search_url, params=dict(term=term))
        if r is None:
            return None

        if r.status_code == 200:
            try:
                # Returned data for each manga:
                # 0: cover path
                # 1: name of the manga
                # 2: slug of the manga
                # 3: UNUSED
                # 4: UNUSED
                data = r.json(strict=False)

                results = []
                for item in data:
                    results.append(dict(
                        slug=item[2],
                        name=item[1],
                    ))

                return results
            except Exception:
                return None

        return None


class Ninemanga_br(Ninemanga):
    # BEWARE: For historical reasons, Id is ninemanga_br instead of ninemanga_pt_br (idem for class name)
    id = 'ninemanga_br'
    name = SERVER_NAME
    lang = 'pt_BR'

    base_url = 'http://br.ninemanga.com'
    search_url = base_url + '/search/ajax/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}'
    page_url = chapter_url


class Ninemanga_de(Ninemanga):
    id = 'ninemanga_de'
    name = SERVER_NAME
    lang = 'de'

    base_url = 'http://de.ninemanga.com'
    search_url = base_url + '/search/ajax/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}'
    page_url = chapter_url


class Ninemanga_es(Ninemanga):
    id = 'ninemanga_es'
    name = SERVER_NAME
    lang = 'es'

    base_url = 'http://es.ninemanga.com'
    search_url = base_url + '/search/ajax/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}'
    page_url = chapter_url


class Ninemanga_fr(Ninemanga):
    id = 'ninemanga_fr'
    name = SERVER_NAME
    lang = 'fr'

    base_url = 'http://fr.ninemanga.com'
    search_url = base_url + '/search/ajax/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}'
    page_url = chapter_url


class Ninemanga_it(Ninemanga):
    id = 'ninemanga_it'
    name = SERVER_NAME
    lang = 'it'

    base_url = 'http://it.ninemanga.com'
    search_url = base_url + '/search/ajax/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}'
    page_url = chapter_url


class Ninemanga_ru(Ninemanga):
    id = 'ninemanga_ru'
    name = SERVER_NAME
    lang = 'ru'

    base_url = 'http://ru.ninemanga.com'
    search_url = base_url + '/search/ajax/'
    most_populars_url = base_url + '/list/Hot-Book/'
    manga_url = base_url + '/manga/{0}.html?waring=1'
    chapter_url = base_url + '/chapter/{0}/{1}'
    page_url = chapter_url
