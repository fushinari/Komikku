# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
from datetime import datetime
import html
import logging

from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

logger = logging.getLogger('komikku.servers.mangadex')

GENRES = {
    '1': '4-koma',
    '2': 'Action',
    '3': 'Adventure',
    '4': 'Award Winning',
    '5': 'Comedy',
    '6': 'Cooking',
    '7': 'Doujinshi',
    '8': 'Drama',
    '9': 'Ecchi',
    '10': 'Fantasy',
    '11': 'Gyaru',
    '12': 'Harem',
    '13': 'Historical',
    '14': 'Horror',
    '16': 'Martial Arts',
    '17': 'Mecha',
    '18': 'Medical',
    '19': 'Music',
    '20': 'Mystery',
    '21': 'Oneshot',
    '22': 'Psychological',
    '23': 'Romance',
    '24': 'School Life',
    '25': 'Sci-Fi',
    '28': 'Shoujo Ai',
    '30': 'Shounen Ai',
    '31': 'Slice of Life',
    '32': 'Smut',
    '33': 'Sports',
    '34': 'Supernatural',
    '35': 'Tragedy',
    '36': 'Long Strip',
    '37': 'Yaoi',
    '38': 'Yuri',
    '40': 'Video Games',
    '41': 'Isekai',
    '42': 'Adaptation',
    '43': 'Anthology',
    '44': 'Web Comic',
    '45': 'Full Color',
    '46': 'User Created',
    '47': 'Official Colored',
    '48': 'Fan Colored',
    '49': 'Gore',
    '50': 'Sexual Violence',
    '51': 'Crime',
    '52': 'Magical Girls',
    '53': 'Philosophical',
    '54': 'Superhero',
    '55': 'Thriller',
    '56': 'Wuxia',
    '57': 'Aliens',
    '58': 'Animals',
    '59': 'Crossdressing',
    '60': 'Demons',
    '61': 'Delinquents',
    '62': 'Genderswap',
    '63': 'Ghosts',
    '64': 'Monster Girls',
    '65': 'Loli',
    '66': 'Magic',
    '67': 'Military',
    '68': 'Monsters',
    '69': 'Ninja',
    '70': 'Office Workers',
    '71': 'Police',
    '72': 'Post-Apocalyptic',
    '73': 'Reincarnation',
    '74': 'Reverse Harem',
    '75': 'Samurai',
    '76': 'Shota',
    '77': 'Survival',
    '78': 'Time Travel',
    '79': 'Vampires',
    '80': 'Traditional Games',
    '81': 'Virtual Reality',
    '82': 'Zombies',
    '83': 'Incest',
}
SERVER_NAME = 'MangaDex'


class Mangadex(Server):
    id = 'mangadex'
    name = SERVER_NAME
    lang = 'en'
    lang_code = 'gb'
    long_strip_genres = ['Long Strip', ]
    has_login = True
    session_expiration_cookies = ['mangadex_rememberme_token', ]

    base_url = 'https://mangadex.org'
    action_url = base_url + '/ajax/actions.ajax.php?function={0}'
    api_manga_url = base_url + '/api/v2/manga/{0}'
    api_chapter_url = base_url + '/api/v2/chapter/{0}'
    search_url = base_url + '/search'
    most_populars_url = base_url + '/titles/7'
    manga_url = base_url + '/title/{0}'
    chapter_url = base_url + '/chapter/{0}'
    page_url = base_url + '/chapter/{0}/{1}'

    headers = {
        'User-Agent': USER_AGENT,
        'Host': 'mangadex.org',
        'Referer': 'https://mangadex.org',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'fr-FR,en-US;q=0.7,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
    }

    def __init__(self, username=None, password=None):
        self.init(username, password)

    @staticmethod
    def convert_old_slug(slug):
        # Removing this will break manga that were added before the change to the manga slug
        return slug.split('/')[0]

    @staticmethod
    def get_group_name(group_id, groups_list):
        """Get group name from group id."""
        matching_group = [group for group in groups_list if group['id'] == group_id]
        return matching_group[0]['name']

    def get_manga_data(self, initial_data):
        """
        Returns manga data from API

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Slug is missing in initial data'

        r = self.session_get(
            self.api_manga_url.format(self.convert_old_slug(initial_data['slug'])),
            headers={
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': '*/*',
                'Referer': self.base_url,
                'Origin': self.base_url,
            },
            params={
                'include': 'chapters'
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()['data']

        data = initial_data.copy()
        data.update(dict(
            authors=[],
            scanlators=[],
            genres=[],
            status=None,
            synopsis=None,
            chapters=[],
            server_id=self.id,
        ))

        data['name'] = html.unescape(resp_data['manga']['title'])
        data['cover'] = resp_data['manga']['mainCover']

        data['authors'] += resp_data['manga']['author']
        data['authors'] += [t for t in resp_data['manga']['artist'] if t not in data['authors']]
        data['genres'] = [GENRES[str(genre_id)] for genre_id in resp_data['manga']['tags'] if str(genre_id) in GENRES]

        if resp_data['manga']['publication']['status'] == 1:
            data['status'] = 'ongoing'
        elif resp_data['manga']['publication']['status'] == 2:
            data['status'] = 'complete'
        elif resp_data['manga']['publication']['status'] == 3:
            data['status'] = 'suspended'
        elif resp_data['manga']['publication']['status'] == 4:
            data['status'] = 'hiatus'

        data['synopsis'] = html.unescape(resp_data['manga']['description'])

        if 'chapters' not in resp_data:
            logger.warning('Chapter information missing')
            return data

        for chapter in resp_data['chapters']:
            if self.lang_code != chapter['language']:
                continue
            if 9097 in chapter['groups']:
                # Chapters from MANGA Plus can't be read from MangaDex
                continue
            if datetime.fromtimestamp(chapter['timestamp']) > datetime.now():
                # Future chapter
                continue

            data['chapters'].append(dict(
                slug=str(chapter['id']),
                title='#{0} - {1}'.format(chapter['chapter'], chapter['title']),
                date=datetime.fromtimestamp(chapter['timestamp']).date(),
                scanlators=[self.get_group_name(group_id, resp_data['groups']) for group_id in chapter['groups']],
            ))

        data['chapters'].reverse()

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url):
        """
        Returns manga chapter data from API

        Currently, only pages are expected.
        """
        r = self.session_get(
            self.api_chapter_url.format(chapter_slug),
            headers={
                'Accept': '*/*',
                'Referer': self.chapter_url.format(chapter_slug),
            }
        )
        if r.status_code != 200:
            return None

        resp_data = r.json()['data']

        data = dict(
            pages=[],
        )
        for page in resp_data['pages']:
            data['pages'].append(dict(
                slug=None,
                image='{0}{1}/{2}'.format(resp_data['server'], resp_data['hash'], page),
            ))

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(page['image'], headers={
            'Accept': 'image/webp,image/*;q=0.8,*/*;q=0.5',
            'Referer': self.page_url.format(chapter_slug, 1),
        })
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
        return self.manga_url.format(slug)

    def get_most_populars(self):
        """ Returns most popular mangas (bayesian rating) """
        r = self.session_get(self.most_populars_url)
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        results = []
        for element in soup.find_all('a', class_='manga_title'):
            results.append(dict(
                slug=element.get('href').replace('/title/', '').split('/')[0],
                name=element.text.strip(),
            ))

        return results

    def login(self, username, password):
        r = self.session_post(
            self.action_url.format('login'),
            data={
                'login_username': username,
                'login_password': password,
                'remember_me': '1',
            },
            headers={
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': '*/*',
                'Referer': 'https://mangadex.org/login',
                'Origin': 'https://mangadex.org'
            }
        )

        if r.text != '':
            return False

        self.save_session()

        return True

    def search(self, term):
        r = self.session_get(self.search_url, params=dict(
            tag_mode_exc='any',
            tag_mode_inc='all',
            title=term,
            s=2,
        ))

        mime_type = get_buffer_mime_type(r.content)
        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        results = []
        for element in soup.find_all('a', class_='manga_title'):
            results.append(dict(
                slug=element.get('href').replace('/title/', ''),
                name=element.text.strip(),
            ))

        return results


class Mangadex_cs(Mangadex):
    id = 'mangadex_cs'
    name = SERVER_NAME
    lang = 'cs'
    lang_code = 'cz'


class Mangadex_de(Mangadex):
    id = 'mangadex_de'
    name = SERVER_NAME
    lang = 'de'
    lang_code = 'de'


class Mangadex_es(Mangadex):
    id = 'mangadex_es'
    name = SERVER_NAME
    lang = 'es'
    lang_code = 'es'


class Mangadex_fr(Mangadex):
    id = 'mangadex_fr'
    name = SERVER_NAME
    lang = 'fr'
    lang_code = 'fr'


class Mangadex_id(Mangadex):
    id = 'mangadex_id'
    name = SERVER_NAME
    lang = 'id'
    lang_code = 'id'


class Mangadex_it(Mangadex):
    id = 'mangadex_it'
    name = SERVER_NAME
    lang = 'it'
    lang_code = 'it'


class Mangadex_ja(Mangadex):
    id = 'mangadex_ja'
    name = SERVER_NAME
    lang = 'ja'
    lang_code = 'jp'


class Mangadex_ko(Mangadex):
    id = 'mangadex_ko'
    name = SERVER_NAME
    lang = 'ko'
    lang_code = 'kr'


class Mangadex_nl(Mangadex):
    id = 'mangadex_nl'
    name = SERVER_NAME
    lang = 'nl'
    lang_code = 'nl'


class Mangadex_pl(Mangadex):
    id = 'mangadex_pl'
    name = SERVER_NAME
    lang = 'pl'
    lang_code = 'pl'


class Mangadex_pt(Mangadex):
    id = 'mangadex_pt'
    name = SERVER_NAME
    lang = 'pt'
    lang_code = 'pt'


class Mangadex_pt_br(Mangadex):
    id = 'mangadex_pt_br'
    name = SERVER_NAME
    lang = 'pt_BR'
    lang_code = 'br'


class Mangadex_ru(Mangadex):
    id = 'mangadex_ru'
    name = SERVER_NAME
    lang = 'ru'
    lang_code = 'ru'


class Mangadex_th(Mangadex):
    id = 'mangadex_th'
    name = SERVER_NAME
    lang = 'th'
    lang_code = 'th'


class Mangadex_vi(Mangadex):
    id = 'mangadex_vi'
    name = SERVER_NAME
    lang = 'vi'
    lang_code = 'vn'


class Mangadex_zh_hans(Mangadex):
    id = 'mangadex_zh_hans'
    name = SERVER_NAME
    lang = 'zh_Hans'
    lang_code = 'cn'


class Mangadex_zh_hant(Mangadex):
    id = 'mangadex_zh_hant'
    name = SERVER_NAME
    lang = 'zh_Hant'
    lang_code = 'hk'
