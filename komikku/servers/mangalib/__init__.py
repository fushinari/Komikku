# -*- coding: utf-8 -*-

# Copyright (C) 2020 GrownNed
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: GrownNed <grownned@gmail.com>

from bs4 import BeautifulSoup
import requests
import json

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server
from komikku.servers import USER_AGENT

headers = {
    'User-Agent': USER_AGENT,
}


class Mangalib(Server):
    id = 'mangalib'
    name = 'MangaLib'
    lang = 'ru'

    base_url = 'https://mangalib.me'
    search_url = base_url + '/manga-list?name={0}'
    most_populars_url = base_url + '/manga-list?sort=views'
    manga_url = base_url + '/{0}'
    chapter_url = manga_url + '/{1}'
    image_url = 'https://img{0}.mangalib.me/{1}'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers = headers

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
        ))

        title_element = soup.find('h1', class_='manga-bg__title')
        if not title_element:
            title_element = soup.find('div', class_='manga-title').h1
        data['name'] = title_element.text.strip()

        cover_element = soup.find('img', class_='manga__cover')
        data['cover'] = cover_element.get('src')

        # Details
        for info in soup.find_all('div', class_='info-list__row'):
            label = info.strong.text.strip()

            if label.startswith('Автор'):
                value = [author.text.strip() for author in info.find_all('a')]
                data['authors'].extend(value)
            elif label.startswith('Художник'):
                value = [author.text.strip() for author in info.find_all('a') if not author.text.strip() in data['authors']]
                data['authors'].extend(value)
            elif label.startswith('Переводчик'):
                value = [scanlator.text.strip() for scanlator in info.find_all('a')]
                data['scanlators'].extend(value)
            elif label.startswith('Перевод'):
                status = info.span.text.strip()
                if status == 'продолжается':
                    data['status'] = 'ongoing'
                elif status == 'завершен':
                    data['status'] = 'complete'
            elif label.startswith('Жанр'):
                value = [genre.text.strip() for genre in info.find_all('a')]
                data['genres'].extend(value)

        # Synopsis
        synopsis_element = soup.find('div', class_='info-desc__content')
        if synopsis_element:
            data['synopsis'] = synopsis_element.text.strip()

        # Chapters
        for element in reversed(soup.find_all('div', class_='chapter-item')):
            a_element = element.find('a')
            if a_element:
                slug = a_element.get('href')[8:].split('/', 2)[2]
            else:
                teams = json.loads(element.get('data-teams'))
                slug = 'v{}/c{}/{}'.format(element.get('data-volume'), element.get('data-number'), teams[0]['slug'])

            title = ' '.join(element.find('div', class_='chapter-item__name').text.split())
            date = element.find('div', class_='chapter-item__date').text.strip()

            data['chapters'].append(dict(
                slug=slug,
                title=title,
                date=convert_date_string(date, format='%d.%m.%Y'),
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

        soup = BeautifulSoup(r.text, 'lxml')

        for script_element in soup.find_all('script'):
            script = script_element.string
            if not script:
                continue

            script = script.strip()
            if script.startswith('window.__info'):
                chapter_json = json.loads(script[16:-1])
            elif script.startswith('window.__pg'):
                pages_json = json.loads(script[14:-1])

        data = dict(
            pages=[dict(
                slug=None,
                image=self.image_url.format(
                    3 if chapter_json['img']['server'] == 'compress' else 2,
                    chapter_json['img']['url'] + page['u']
                ),
            ) for page in pages_json]
        )

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
            name=page['image'].split('/')[-1].split('?')[0],
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url.format(slug)

    def get_most_populars(self):
        """ Returns best noted manga list """
        r = self.session_get(self.most_populars_url)
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for card in soup.find_all('a', class_='media-card'):
            results.append(dict(
                name=card.div.h3.text.strip(),
                slug=card.get('href').split('/')[-1],
            ))

        return results

    def search(self, term):
        r = self.session_get(self.search_url.format(term))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for card in soup.find_all('a', class_='media-card'):
            results.append(dict(
                name=card.div.h3.text.strip(),
                slug=card.get('href').split('/')[-1],
            ))

        return sorted(results, key=lambda m: m['name'])


# NSFW
class Hentailib(Mangalib):
    id = 'hentailib:mangalib'
    name = 'HentaiLib'
    lang = 'ru'
    is_nsfw = True

    base_url = 'https://hentailib.me'
    search_url = base_url + '/manga-list?name={0}'
    most_populars_url = base_url + '/manga-list?sort=views'
    manga_url = base_url + '/{0}'
    chapter_url = manga_url + '/{1}'
    image_url = 'https://img{0}.hentailib.me{1}'
