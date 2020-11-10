# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import base64
from bs4 import BeautifulSoup
import json
import re
import requests

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

re_chapter_date = re.compile(r'\d{4}.\d{2}.\d{2}')

# All theses servers use FoOlSlide Open Source online comic management software (NO LONGER MAINTAINED)
# https://github.com/FoolCode/FoOlSlide or https://github.com/chocolatkey/FoOlSlide2 (fork)

#
# BEWARE: Jaimini's Box server is disabled
# Dead since 07/09/2020
#


class Jaiminisbox(Server):
    id = 'jaiminisbox'
    name = "Jaimini's Box"
    lang = 'en'
    status = 'disabled'

    base_url = 'https://jaiminisbox.com/reader'
    search_url = base_url + '/search'
    mangas_url = base_url + '/directory'
    manga_url = base_url + '/series/{0}'
    chapter_url = base_url + '/read/{0}/en/{1}/page/1'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

    @staticmethod
    def decrypt(value):
        """
        Decrypt a string with a circular shift of 13 of [a-zA-Z] characters

        nopqrstuvwxyzabcdefghijklm => abcdefghijklmnopqrstuvwxyz
        """
        dvalue = ''

        for char in value:
            code = ord(char)
            if 65 <= code <= 77 or 97 <= code <= 109:
                dvalue += chr(code + 13)
            elif 78 <= code <= 90 or 110 <= code <= 122:
                dvalue += chr(code - 13)
            else:
                dvalue += char

        return dvalue

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

        adult_alert = False
        if soup.find('div', class_='alert'):
            adult_alert = True

            r = self.session_post(self.manga_url.format(initial_data['slug']), data=dict(adult='true'))
            if r is None:
                return None

            soup = BeautifulSoup(r.text, 'html.parser')

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[self.name, ],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
            cover=None,
        ))

        data['name'] = soup.find('h1', class_='title').text.strip()
        if soup.find('div', class_='thumbnail'):
            data['cover'] = soup.find('div', class_='thumbnail').img.get('src')

        # Details
        for element in soup.find('div', class_='info').find_all('b'):
            label = element.text
            value = list(element.next_siblings)[0][2:]
            if label in ('Author', 'Artist'):
                data['authors'].append(value)
            elif label in ('Description', 'Synopsis', ):
                if adult_alert:
                    data['synopsis'] = '{0}\n\n{1}'.format(
                        'ALERT: This series contains mature contents and is meant to be viewed by an adult audience.',
                        value
                    )
                else:
                    data['synopsis'] = value

        # Chapters
        for element in reversed(soup.find('div', class_='list').find_all('div', class_='element')):
            a_element = element.find('div', class_='title').a

            title = a_element.text.strip()
            slug = a_element.get('href').replace(f'{self.base_url}/read/{initial_data["slug"]}/{self.lang}/', '')[:-1]

            date_match = re.search(re_chapter_date, element.find('div', class_='meta_r').text)
            if date_match:
                date = convert_date_string(date_match.group(), '%Y.%m.%d')
            else:
                date = None

            data['chapters'].append(dict(
                slug=slug,
                date=date,
                title=title,
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages are expected.
        """
        r = self.session_post(self.chapter_url.format(manga_slug, chapter_slug), data=dict(adult='true'))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        # List of pages is available in JavaScript variable '_0x3320' or 'pages'
        # Walk in all scripts to find it
        pages = None
        for script_element in soup.find_all('script'):
            script = script_element.string
            if script is None:
                continue

            for line in script.split('\n'):
                line = line.strip()
                if line.startswith('var _0x3320'):
                    #
                    # Jaimini's Box
                    #
                    pages = line.split(';')[0].split(',')[1][1:-2]
                    # String is encrypted with a circular shift of 13 for [a-zA-Z] characters
                    pages = self.decrypt(pages)
                    # String is BASE64 encoded
                    pages = base64.b64decode(pages)
                    break
                if line.startswith('var pages'):
                    #
                    # Kirei Cake
                    #
                    pages = line.replace('var pages = ', '')[:-1]
                    break
            if pages is not None:
                pages = json.loads(pages)
                break

        if pages is None:
            return None

        data = dict(
            pages=[],
        )
        for page in pages:
            data['pages'].append(dict(
                slug=None,
                image=page['url'],
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(page['image'])
        if r is None or r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['image'].split('?')[0].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url.format(slug)

    def get_mangas(self, page=1):
        r = self.session_get('{0}/{1}'.format(self.mangas_url, page))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        results = []
        for element in soup.find('div', class_='series').find_all('div', class_='group'):
            a_element = element.find('div', class_='title').a

            results.append(dict(
                slug=a_element.get('href').split('/')[-2],
                name=a_element.get('title'),
            ))

        return results

    def get_most_populars(self):
        """ Returns list of all mangas """
        r = self.session_get(self.mangas_url)
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        nav_buttons = soup.find_all('a', class_='gbutton')
        if nav_buttons:
            nb_pages = int(nav_buttons[0].get('href').split('/')[-2])
        else:
            nb_pages = 1

        results = []
        for index in range(nb_pages):
            results += self.get_mangas(page=index + 1)

        return results

    def search(self, term):
        r = self.session_post(self.search_url, data=dict(search=term))
        if r is None:
            return None

        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')

            results = []
            for element in soup.find('div', class_='list').find_all('div', class_='group'):
                a_element = element.find_all('div')[0].a

                results.append(dict(
                    slug=a_element.get('href').split('/')[-2],
                    name=a_element.get('title'),
                ))

            return results

        return None


class Kireicake(Jaiminisbox):
    id = 'kireicake:jaiminisbox'
    name = 'Kirei Cake'
    lang = 'en'
    status = 'enabled'

    base_url = 'https://reader.kireicake.com'
    search_url = base_url + '/search'
    mangas_url = base_url + '/directory'
    manga_url = base_url + '/series/{0}'
    chapter_url = base_url + '/read/{0}/en/{1}/page/1'


class Lupiteam(Jaiminisbox):
    id = 'lupiteam:jaiminisbox'
    name = 'Lupi Team'
    lang = 'it'
    status = 'enabled'

    base_url = 'https://lupiteam.net/reader'
    search_url = base_url + '/search'
    mangas_url = base_url + '/directory'
    manga_url = base_url + '/series/{0}'
    chapter_url = base_url + '/read/{0}/it/{1}/page/1'


class Tuttoanimemanga(Jaiminisbox):
    id = 'tuttoanimemanga:jaiminisbox'
    name = 'Tutto Anime Manga'
    lang = 'it'
    status = 'enabled'

    base_url = 'http://tuttoanimemanga.net/slide'
    search_url = base_url + '/search'
    mangas_url = base_url + '/directory'
    manga_url = base_url + '/series/{0}'
    chapter_url = base_url + '/read/{0}/it/{1}/page/1'
