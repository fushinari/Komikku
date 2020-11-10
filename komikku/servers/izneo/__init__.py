# -*- coding: utf-8 -*-

# Copyright (C) 2020 tijder
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: tijder

from bs4 import BeautifulSoup
import datetime
import json

from komikku.servers import get_buffer_mime_type
from komikku.servers import Server


class Izneo(Server):
    id = 'izneo'
    name = 'Izneo'
    lang = 'en'
    has_login = True
    session_expiration_cookies = ['remember_me', ]

    base_url = 'https://www.izneo.com'
    base_reader_url = 'https://reader.izneo.com'
    login_url = base_url + '/nl/login'
    api_manga_url = base_url + '/nl/api/serie/top/{0}?abo=0'
    api_chapter_url = base_url + '/nl/api/library/detail/{0}?offset={1}&order=10&text='
    cover_url = base_url + '/nl/images/album/{0}-275or365.jpg?v=undefined'
    chapters_url = base_reader_url + '/read/{0}?startpage=1'
    user_collection_url = base_url + '/nl/api/library?offset={0}&order=3&text={1}'

    def __init__(self, username=None, password=None):
        self.init(username, password)

    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial_data'
        r = self.session_get(self.api_manga_url.format(initial_data['slug']))

        try:
            resp_data = r.json()
        except Exception:
            return None

        data = initial_data.copy()
        data.update(dict(
            name=resp_data['name'],
            authors=[author['nickname'] for author in resp_data['authors']],
            scanlators=[],
            genres=[resp_data['gender']],
            status='ongoing',
            chapters=[],
            synopsis=resp_data['synopsis'],
            cover=self.cover_url.format(resp_data['ean_last_album']),
            server_id=self.id,
            url=resp_data['url'],
        ))

        # Chapters
        offset = 0
        while offset is not None:
            r = self.session_get(self.api_chapter_url.format(initial_data['slug'], offset))
            offset += 1
            resp_data = r.json()
            if 'albums' not in resp_data:
                offset = None
                continue

            for chapter in resp_data['albums'][str(offset)]:
                title = chapter['title']
                if chapter['volume']:
                    title = '{0} - {1}'.format(chapter['volume'], title)

                data['chapters'].append(dict(
                    slug=chapter['ean'],
                    title=title,
                    date=datetime.datetime.fromtimestamp(chapter['version']).date(),
                ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data

        Currently, only pages are expected.
        """
        r = self.session_get(self.chapters_url.format(chapter_slug))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.content, 'lxml')

        script_content = soup.find('script').string.strip()
        pages = json.loads(script_content.split('resourcesIndex               = ')[1].split(';')[0])

        data = dict(
            pages=[],
        )

        for page in pages:
            if page['id'] != 'endingpage':
                data['pages'].append(dict(
                    slug=None,
                    image=page['url'],
                ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(self.base_reader_url + page['image'])
        if r.status_code != 200:
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
        return self.base_url + url

    def get_most_populars(self):
        """ Returns all series available in user's collection """
        return self.search_in_user_collection('')

    def login(self, username, password):
        if not username or not password:
            return False

        r = self.session_get(self.login_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.content, 'lxml')

        self.session_post(
            self.login_url,
            data={
                'form[username]': username,
                'form[password]': password,
                'form[remember_me]': '1',
                'form[_token]': soup.findAll('input', {'type': 'hidden'})[0].get('value'),
            }
        )

        r = self.session_get(self.user_collection_url.format(0, ''))
        try:
            if 'error' in r.json():
                return False
        except Exception:
            return False

        self.save_session()

        return True

    def search(self, term):
        return self.search_in_user_collection(term)

    def search_in_user_collection(self, term):
        results = []
        offset = 0
        while offset is not None:
            r = self.session_get(self.user_collection_url.format(offset, term))
            if r.status_code != 200:
                return None

            offset += 1
            try:
                resp_data = r.json()
            except Exception:
                return None

            if 'error' in resp_data:
                # Not logged in
                return None

            if 'series' not in resp_data:
                # No more mangas to load
                offset = None
                continue

            for serie in resp_data['series']:
                results.append(dict(
                    name=serie['name'],
                    slug=serie['id'],
                ))

        return results


class Izneo_de(Izneo):
    id = 'izneo_de'
    name = 'Izneo'
    lang = 'de'


class Izneo_fr(Izneo):
    id = 'izneo_fr'
    name = 'Izneo'
    lang = 'fr'


class Yieha(Izneo):
    id = 'yieha:izneo'
    name = 'Yieha'
    lang = 'nl'
