# -*- coding: utf-8 -*-

# Copyright (C) 2020 GrownNed
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: GrownNed <grownned@gmail.com>

from bs4 import BeautifulSoup
import re
import requests

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import Server


class Readmanga(Server):
    id = 'readmanga'
    name = 'Read Manga'
    lang = 'ru'

    base_url = 'https://readmanga.live'
    search_url = base_url + '/search/advanced'
    most_populars_url = base_url + '/list?sortType=rate'
    manga_url = base_url + '/{0}'
    chapter_url = manga_url + '/{1}?mtr=1'

    def __init__(self):
        if self.session is None:
            self.session = requests.Session()

    def get_manga_data(self, initial_data):
        """
        Returns manga data by scraping manga HTML page content

        Initial data should contain at least manga's slug (provided by search)
        """
        assert 'slug' in initial_data, 'Manga slug is missing in initial data'

        r = self.session_get(self.manga_url.format(initial_data['slug']))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
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

        info_element = soup.find('div', class_='leftContent')

        title_element = info_element.find('span', class_='name')
        data['name'] = title_element.text.strip()

        cover_element = info_element.find('img', attrs={'data-full': True})
        data['cover'] = cover_element.get('data-full')

        # Details
        elements = info_element.find('div', class_='subject-meta').find_all('p', recursive=False)

        status = elements[1].find(text=True, recursive=False).strip()
        if status == 'продолжается':
            data['status'] = 'ongoing'
        elif status == 'завершен':
            data['status'] = 'complete'

        for element in elements[2:]:
            label = element.span.text.strip()

            if label.startswith('Автор') or label.startswith('Сценарист') or label.startswith('Художник'):
                value = [author.text.strip() for author in element.find_all('a', class_='person-link')]
                data['authors'].extend(value)
            elif label.startswith('Переводчик'):
                value = [scanlator.text.strip() for scanlator in element.find_all('a', class_='person-link')]
                data['scanlators'].extend(value)
            elif label.startswith('Жанр'):
                value = [genre.text.strip() for genre in element.find_all('a', class_='element-link')]
                data['genres'].extend(value)

        # Synopsis
        data['synopsis'] = info_element.find('div', class_='manga-description').text.strip()

        # Chapters
        chapters_element = info_element.find('div', class_='chapters-link', recursive=False)
        if not chapters_element:
            return data

        for element in reversed(chapters_element.table.find_all('tr', recursive=False)):
            a_element = element.find('a')
            slug = a_element.get('href').split('/', 2)[2]
            title = a_element.find(text=True, recursive=False).strip()
            date = element.find('td', align='right').text.strip()

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
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        data = dict(
            pages=[],
        )

        for script_element in soup.find_all('script'):
            script = script_element.string
            if not script or not script.strip().startswith('var prevLink'):
                continue

            for line in script.split('\n'):
                line = line.strip()
                if not line.startswith('rm_h.init'):
                    continue

                pattern = re.compile('\'.*?\',\'.*?\',".*?"')
                for urls in pattern.findall(line):
                    urls = urls.replace('\'', '').replace('"', '').split(',')
                    data['pages'].append(dict(
                        slug=None,
                        image=urls[0] + urls[2],
                    ))
                break
            break

        return data

    def get_manga_chapter_page_image(self, manga_slug, manga_name, chapter_slug, page):
        """ Returns chapter page scan (image) content """
        r = self.session_get(page['image'])
        if r.status_code != 200:
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
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for h3_element in soup.find('div', class_='tiles').find_all('h3'):
            if not h3_element.a:
                continue
            results.append(dict(
                name=h3_element.a.get('title').strip(),
                slug=h3_element.a.get('href')[1:],
            ))

        return results

    def search(self, term):
        r = self.session_get(self.search_url, params=dict(q=term))
        if r.status_code != 200:
            return None

        mime_type = get_buffer_mime_type(r.content)
        if mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for h3_element in soup.find_all('h3')[1:]:
            results.append(dict(
                name=h3_element.a.text.strip(),
                slug=h3_element.a.get('href')[1:],
            ))

        return sorted(results, key=lambda m: m['name'])


class Mintmanga(Readmanga):
    id = 'mintmanga:readmanga'
    name = 'Mint Manga'

    base_url = 'https://mintmanga.live'
    search_url = base_url + '/search/advanced'
    most_populars_url = base_url + '/list?sortType=rate'
    manga_url = base_url + '/{0}'
    chapter_url = manga_url + '/{1}?mtr=1'


class Selfmanga(Readmanga):
    id = 'selfmanga:readmanga'
    name = 'Self Manga'

    base_url = 'https://selfmanga.live'
    search_url = base_url + '/search/advanced'
    most_populars_url = base_url + '/list?sortType=rate'
    manga_url = base_url + '/{0}'
    chapter_url = manga_url + '/{1}?mtr=1'
