# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import requests

from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

# Conversion ISO_639-1 codes => server codes
LANGUAGES_CODES = dict(
    cs='cs',
    de='de',
    en='en',
    es='es',
    fr='fr',
    id='id',
    it='it',
    ja='ja',
    ko='kr',  # diff
    nb='no',  # diff
    nl='nl',
    pl='pl',
    pt='pt',
    ru='ru',
    vi='vi',
    zh_Hans='cn',  # diff
)

SERVER_NAME = 'Pepper&Carrot'


class Peppercarrot(Server):
    id = 'peppercarrot'
    name = SERVER_NAME
    lang = 'en'

    base_url = 'https://www.peppercarrot.com'
    manga_url = base_url + '/{0}/'
    chapters_url = base_url + '/0_sources/episodes-v1.json'
    image_url = base_url + '/0_sources/{0}/low-res/{1}_{2}'
    cover_url = base_url + '/0_sources/0ther/artworks/low-res/2016-02-24_vertical-cover_remake_by-David-Revoy.jpg'

    synopsis = 'This is the story of the young witch Pepper and her cat Carrot in the magical world of Hereva. Pepper learns the magic of Chaosah, the magic of chaos, with his godmothers Cayenne, Thyme and Cumin. Other witches like Saffron, Coriander, Camomile and Schichimi learn magics that each have their specificities.'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'user-agent': USER_AGENT})

    def get_manga_data(self, initial_data):
        """ Returns manga data by scraping manga HTML page content """
        r = self.session_get(self.manga_url.format(LANGUAGES_CODES[self.lang]))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        data = initial_data.copy()
        data.update(dict(
            authors=['David Revoy', ],
            scanlators=[],
            genres=[],
            status='ongoing',
            synopsis=self.synopsis,
            chapters=[],
            server_id=self.id,
            cover=self.cover_url,
        ))

        r = self.session_get(self.chapters_url)
        if r is None:
            return None

        chapters_data = r.json()

        # Chapters
        for index, element in enumerate(reversed(soup.find('div', class_='homecontent').find_all('figure'))):
            if 'notranslation' in element.get('class'):
                # Skipped not translated episodes
                continue

            data['chapters'].append(dict(
                slug=chapters_data[index]['name'],
                date=None,
                title=element.a.get('title'),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """ Returns manga chapter data using episodes API service """
        r = self.session_get(self.chapters_url)
        if r is None:
            return None

        chapters_data = r.json()
        for chapter_data in chapters_data:
            if chapter_data['name'] == chapter_slug:
                break

        data = dict(
            pages=[],
        )

        # Cover & Title pages are first
        data['pages'].append(dict(
            slug=chapter_data['pages']['cover'],
            image=None,
        ))
        data['pages'].append(dict(
            slug=chapter_data['pages']['title'],
            image=None,
        ))

        for key, page_name in chapter_data['pages'].items():
            if key in ('cover', 'title', ):
                # Skipped cover and title pages
                continue

            data['pages'].append(dict(
                slug=page_name,
                image=None,
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(self.image_url.format(chapter_slug, LANGUAGES_CODES[self.lang], page['slug']))
        if r is None or r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if not mime_type.startswith('image'):
            return None

        return dict(
            buffer=r.content,
            mime_type=mime_type,
            name=page['slug'],
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url.format(LANGUAGES_CODES[self.lang])

    def get_most_populars(self):
        return self.search()

    @staticmethod
    def search(term=None):
        return [dict(
            slug='',
            name='Pepper&Carrot',
        )]


class Peppercarrot_cs(Peppercarrot):
    id = 'peppercarrot_cs'
    name = SERVER_NAME
    lang = 'cs'


class Peppercarrot_de(Peppercarrot):
    id = 'peppercarrot_de'
    name = SERVER_NAME
    lang = 'de'


class Peppercarrot_es(Peppercarrot):
    id = 'peppercarrot_es'
    name = SERVER_NAME
    lang = 'es'


class Peppercarrot_fr(Peppercarrot):
    id = 'peppercarrot_fr'
    name = SERVER_NAME
    lang = 'fr'

    synopsis = "C'est l'histoire de la jeune sorcière Pepper et de son chat Carrot dans le monde magique d'Hereva. Pepper apprend la magie de Chaosah, la magie du chaos, avec ses marraines Cayenne, Thym et Cumin. D'autres sorcières comme Saffran, Coriandre, Camomille et Schichimi apprennent des magies qui ont chacune leurs spécificités."


class Peppercarrot_id(Peppercarrot):
    id = 'peppercarrot_id'
    name = SERVER_NAME
    lang = 'id'


class Peppercarrot_it(Peppercarrot):
    id = 'peppercarrot_it'
    name = SERVER_NAME
    lang = 'it'


class Peppercarrot_ja(Peppercarrot):
    id = 'peppercarrot_ja'
    name = SERVER_NAME
    lang = 'ja'


class Peppercarrot_ko(Peppercarrot):
    id = 'peppercarrot_ko'
    name = SERVER_NAME
    lang = 'ko'


class Peppercarrot_nb(Peppercarrot):
    id = 'peppercarrot_nb'
    name = SERVER_NAME
    lang = 'nb'


class Peppercarrot_nl(Peppercarrot):
    id = 'peppercarrot_nl'
    name = SERVER_NAME
    lang = 'nl'


class Peppercarrot_pl(Peppercarrot):
    id = 'peppercarrot_pl'
    name = SERVER_NAME
    lang = 'pl'


class Peppercarrot_pt(Peppercarrot):
    id = 'peppercarrot_pt'
    name = SERVER_NAME
    lang = 'pt'


class Peppercarrot_ru(Peppercarrot):
    id = 'peppercarrot_ru'
    name = SERVER_NAME
    lang = 'ru'


class Peppercarrot_vi(Peppercarrot):
    id = 'peppercarrot_vi'
    name = SERVER_NAME
    lang = 'vi'


class Peppercarrot_zh_hans(Peppercarrot):
    id = 'peppercarrot_zh_hans'
    name = SERVER_NAME
    lang = 'zh_Hans'
