# -*- coding: utf-8 -*-

# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

from bs4 import BeautifulSoup
import cloudscraper
from urllib.parse import urlsplit

from komikku.servers import convert_date_string
from komikku.servers import get_buffer_mime_type
from komikku.servers import search_duckduckgo
from komikku.servers import Server


class Japscan(Server):
    id = 'japscan'
    name = 'JapScan'
    lang = 'fr'
    long_strip_genres = ['Webtoon', ]

    base_url = 'https://www.japscan.se'
    search_url = base_url + '/manga/'
    api_search_url = base_url + '/live-search/'
    manga_url = base_url + '/manga/{0}/'
    chapter_url = base_url + '/lecture-en-ligne/{0}/{1}/'
    image_url = 'https://c.japscan.se/lel/{0}/{1}/{2}'
    cover_url = base_url + '{0}'

    def __init__(self):
        if self.session is None:
            self.session = cloudscraper.create_scraper()

    def compute_cipher_alphabet(self):
        """
        Substitution cipher: each letter is replaced with another letter (arbitrarily shuffled alphabet)

        Cipher is updated in short intervals. Alphabet must be recomputed each time new chapter data are fetched.
        """

        alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
        cipher_alphabet = list(alphabet)
        references = [
            {
                'manga_slug': 'bloody-kiss',
                'chapter_slug': 'volume-1',
                'pages': {
                    1: '221518b2f9a20842e4c5379223a5881255d2e522c32277923242520284a542f28085b952e422b1e5a97216b262e5e6621535a22/552c5c112f3e2c4f2e122f025517294925042f322d54513e25822c7e2ev0274751116a4266386a0d56w2506a578b562f6exd2e6/65f435e996fs95fw1160125x715062eve104e33va38454bu632x1315b4fxa10244e2c438932ta38v1158d4e323cx237x933u435/1038xa1',
                    3: 'a336f98370e3d9130516d873045639a35633468374c3389353f36313759623633176406345c3e2e60033e713c37687239616b3f6732612a3d4437/5738213e1d642b3d5a3f113d4e3b666c423e973a8d3bja3a50662772597a4270196akc6b74609a613277l1337d6c0776ge60k3220735l85410640/33a25325d2a927b446al56al36fi8672e4dl120113dj7205543ja455354i847lc436955lf26315739529643h744j6249c5e4e40l34el14ci74822/49l12',
                    13: '4033163017801660626355d0118326c0c3202380719055b0e070e020a2e3d0c04883e750d2a029f397704470f0e3a4208303f0b370a37930816022/f0097038e3a9a0e2c0781021d0f303a120f6d075b05nd0e27379d48204b164f8a36od374a3c6f3e0b4fpa0841357f44kc3co798740c8c02p924853/e7b0398052d996e491534p331p331m8319616p6958d01n8922c1cn2122827m915pb1e372ep29a0e2d0c24681el51dna926f291714p71fpe1am2189/01fpb9',
                    28: 'e952450996d945591172e4b9e0528549828912293089e469a939a939c172c9d997b276f991c9a842566973f96922e359c222f9b21/932984980e931e908d98742f819f179a7a9d0c972e2a07975794419az6931c248032173809377523a028322b51279a3fbf903e2d6/03dw72bae8a6399bd1f7f26bf8d7196za85140fz00d121ey504b0092d14b581971e9b1e5508x408z8815213080eb60ab30ay30c87/0cbd8',
                },
            },
            {
                'manga_slug': '1-nen-a-gumi-no-monster',
                'chapter_slug': '1',
                'pages': {
                    0: 'd7b023a0f83391903313f630b090311054d04910118397b0c140003368b3e3d343e0a390a76032c0d990f16387104953d110405378d030/4388f0d7a052f05820e853203377a04760e06034a0c5b019c05p805223198472d41174f863aqe394f3e6c32014ar30642387f41m13dqe9/f8a0f7700rf95890era9a9e26211a1a29062dqb12ra1fp319p993r11fq31bp9936115pd1421214819pb9c8410p396qb1e2d14qe1ap99a8/603rc9',
                },
            },
        ]

        for reference in references:
            # Get encoded pages paths
            chapter_data = self.get_manga_chapter_data(reference['manga_slug'], None, reference['chapter_slug'], None, decode=False)
            if not chapter_data or not chapter_data.get('pages'):
                return None, None

            encoded_pages = chapter_data['pages']
            for number, path in reference['pages'].items():
                for index, char in enumerate(path):
                    encoded_char = encoded_pages[number]['image'][index]
                    if char == encoded_char:
                        continue

                    cipher_alphabet[alphabet.find(encoded_char)] = char

        return ''.join(cipher_alphabet), alphabet

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
            scanlators=[],
            genres=[],
            status=None,
            chapters=[],
            server_id=self.id,
            synopsis=None,
        ))

        card_element = soup.find_all('div', class_='card')[0]

        # Main name: japscan handles several names for mangas (main + alternatives)
        # Name provided by search can be one of the alternatives
        # First word (Manga, Manhwa, ...) must be removed from name
        data['name'] = ' '.join(card_element.find('h1').text.strip().split()[1:])
        if data.get('cover') is None:
            data['cover'] = self.cover_url.format(card_element.find('img').get('src'))

        # Details
        if not card_element.find_all('div', class_='d-flex'):
            # mobile version
            elements = card_element.find_all('div', class_='row')[0].find_all('p')
        else:
            # desktop version
            elements = card_element.find_all('div', class_='d-flex')[0].find_all('p', class_='mb-2')

        for element in elements:
            label = element.span.text
            element.span.extract()
            value = element.text.strip()

            if label.startswith(('Auteur', 'Artiste')):
                for t in value.split(','):
                    t = t.strip()
                    if t not in data['authors']:
                        data['authors'].append(t)
            elif label.startswith('Genre'):
                data['genres'] = [genre.strip() for genre in value.split(',')]
            elif label.startswith('Statut'):
                # Possible values: ongoing, complete
                data['status'] = 'ongoing' if value == 'En Cours' else 'complete'

        # Synopsis
        synopsis_element = card_element.find('p', class_='list-group-item-primary')
        if synopsis_element:
            data['synopsis'] = synopsis_element.text.strip()

        # Chapters
        elements = soup.find('div', id='chapters_list').find_all('div', class_='chapters_list')
        for element in reversed(elements):
            if element.a.span:
                span = element.a.span.extract()
                # JapScan sometimes uploads some "spoiler preview" chapters, containing 2 or 3 untranslated pictures taken from a raw.
                # Sometimes they also upload full RAWs/US versions and replace them with a translation as soon as available.
                # Those have a span.badge "SPOILER", "RAW" or "VUS". We exclude these from the chapters list.
                if span.text.strip() in ('RAW', 'SPOILER', 'VUS', ):
                    continue

            slug = element.a.get('href').split('/')[3]

            data['chapters'].append(dict(
                slug=slug,
                title=element.a.text.strip(),
                date=convert_date_string(element.span.text.strip(), format='%d %b %Y'),
            ))

        return data

    def get_manga_chapter_data(self, manga_slug, manga_name, chapter_slug, chapter_url, decode=True):
        """
        Returns manga chapter data by scraping chapter HTML page content

        Currently, only pages and scrambled are expected.
        """
        r = self.session_get(self.chapter_url.format(manga_slug, chapter_slug))
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        data = dict(
            pages=[],
            scrambled=0,
        )

        soup = BeautifulSoup(r.text, 'html.parser')

        # Scrambled ?
        for script in soup.find('head').find_all('script'):
            src = script.get('src')
            if src and src.startswith('/js/iYFbYi_U'):
                data['scrambled'] = 1
                break

        if decode:
            cipher_alphabet, alphabet = self.compute_cipher_alphabet()
            if cipher_alphabet is None:
                return None

        pages_options = soup.find('select', id='pages').find_all('option')
        for option in pages_options:
            url_split = urlsplit(option.get('data-img'))
            path, extension = url_split.path.split('.')

            if decode:
                decoded_path = ''.join(cipher_alphabet[alphabet.find(char)] if alphabet.find(char) >= 0 else char for char in path)

                data['pages'].append(dict(
                    slug=None,
                    image=f'{url_split.scheme}://{url_split.netloc}{decoded_path}.{extension}',
                ))
            else:
                data['pages'].append(dict(
                    slug=None,
                    image=path[1:],
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
            name=page['image'].split('/')[-1],
        )

    def get_manga_url(self, slug, url):
        """ Returns manga absolute URL """
        return self.manga_url.format(slug)

    def get_most_populars(self):
        """ Returns TOP manga """
        r = self.session_get(self.base_url)
        if r is None:
            return None

        mime_type = get_buffer_mime_type(r.content)

        if r.status_code != 200 or mime_type != 'text/html':
            return None

        soup = BeautifulSoup(r.text, 'lxml')

        results = []
        for li_element in soup.find('div', id='top_mangas_all_time').find_all('li'):
            a_element = li_element.find_all('a')[0]
            results.append(dict(
                name=a_element.text.strip(),
                slug=a_element.get('href').split('/')[-2],
            ))

        return results

    def search(self, term):
        r = self.session_post(self.api_search_url, data=dict(search=term), headers={
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': '*/*',
            'Origin': self.base_url,
        })
        if r is None:
            return None

        if r.status_code == 200:
            try:
                data = r.json()

                results = []
                for item in data:
                    results.append(dict(
                        slug=item['url'].split('/')[-2],
                        name=item['name'],
                    ))

                return results
            except Exception:
                pass

        # Use DuckDuckGo Lite as fallback
        results = []
        for ddg_result in search_duckduckgo(self.search_url, term):
            # Remove first word in name (Manga, Manhua, Manhwa...)
            name = ' '.join(ddg_result['name'].split()[1:])
            # Keep only words before "|" character
            name = name.split('|')[0].strip()

            results.append(dict(
                name=name,
                slug=ddg_result['url'].split('/')[-2],
            ))

        return results
