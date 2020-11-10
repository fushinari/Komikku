# Copyright (C) 2019-2020 Valéry Febvre
# SPDX-License-Identifier: GPL-3.0-only or GPL-3.0-or-later
# Author: Valéry Febvre <vfebvre@easter-eggs.com>

import datetime
from functools import lru_cache
from gettext import gettext as _
import importlib
import json
import logging
import os
from PIL import Image
import sqlite3
import shutil

from komikku.models.settings import Settings
from komikku.servers import convert_image
from komikku.servers import get_server_class_name_by_id
from komikku.servers import get_server_dir_name_by_id
from komikku.servers import get_server_module_name_by_id
from komikku.servers import unscramble_image
from komikku.utils import get_data_dir

logger = logging.getLogger('komikku')

VERSION = 6


def adapt_json(data):
    return (json.dumps(data, sort_keys=True)).encode()


def convert_json(blob):
    return json.loads(blob.decode())


sqlite3.register_adapter(dict, adapt_json)
sqlite3.register_adapter(list, adapt_json)
sqlite3.register_adapter(tuple, adapt_json)
sqlite3.register_converter('json', convert_json)


def backup_db():
    db_path = get_db_path()
    if os.path.exists(db_path) and check_db():
        print('Save a DB backup')
        shutil.copyfile(db_path, get_db_backup_path())


def check_db():
    db_conn = create_db_connection()

    if db_conn:
        res = db_conn.execute('PRAGMA integrity_check').fetchone()  # PRAGMA quick_check

        fk_violations = len(db_conn.execute('PRAGMA foreign_key_check').fetchall())

        db_conn.close()

        return res[0] == 'ok' and fk_violations == 0

    return False


def create_db_connection():
    con = sqlite3.connect(get_db_path(), detect_types=sqlite3.PARSE_DECLTYPES)
    if con is None:
        print("Error: Can not create the database connection.")
        return None

    con.row_factory = sqlite3.Row

    # Enable integrity constraint
    con.execute('PRAGMA foreign_keys = ON')

    return con


def execute_sql(conn, sql):
    try:
        c = conn.cursor()
        c.execute(sql)
        return True
    except Exception as e:
        print('SQLite-error:', e)
        return False


@lru_cache(maxsize=None)
def get_db_path():
    return os.path.join(get_data_dir(), 'komikku.db')


@lru_cache(maxsize=None)
def get_db_backup_path():
    return os.path.join(get_data_dir(), 'komikku_backup.db')


def init_db():
    db_path = get_db_path()
    db_backup_path = get_db_backup_path()
    if os.path.exists(db_path) and os.path.exists(db_backup_path) and not check_db():
        # Restore backup
        print('Restore DB from backup')
        shutil.copyfile(db_backup_path, db_path)

    sql_create_mangas_table = """CREATE TABLE IF NOT EXISTS mangas (
        id integer PRIMARY KEY,
        slug text NOT NULL,
        url text, -- only used in case slug can't be used to forge the url
        server_id text NOT NULL,
        name text NOT NULL,
        authors json,
        scanlators json,
        genres json,
        synopsis text,
        status text,
        background_color text,
        borders_crop integer,
        reading_mode text,
        scaling text,
        sort_order text,
        last_read timestamp,
        last_update timestamp,
        UNIQUE (slug, server_id)
    );"""

    sql_create_chapters_table = """CREATE TABLE IF NOT EXISTS chapters (
        id integer PRIMARY KEY,
        manga_id integer REFERENCES mangas(id) ON DELETE CASCADE,
        slug text NOT NULL,
        url text, -- only used in case slug can't be used to forge the url
        title text NOT NULL,
        scanlators json,
        pages json,
        scrambled integer,
        date date,
        rank integer NOT NULL,
        downloaded integer NOT NULL,
        recent integer NOT NULL,
        read integer NOT NULL,
        last_page_read_index integer,
        UNIQUE (slug, manga_id)
    );"""

    sql_create_downloads_table = """CREATE TABLE IF NOT EXISTS downloads (
        id integer PRIMARY KEY,
        chapter_id integer REFERENCES chapters(id) ON DELETE CASCADE,
        status text NOT NULL,
        percent float NOT NULL,
        errors integer DEFAULT 0,
        date timestamp NOT NULL,
        UNIQUE (chapter_id)
    );"""

    db_conn = create_db_connection()
    if db_conn is not None:
        db_version = db_conn.execute('PRAGMA user_version').fetchone()[0]

        if db_version == 0:
            # First launch
            execute_sql(db_conn, sql_create_mangas_table)
            execute_sql(db_conn, sql_create_chapters_table)
            execute_sql(db_conn, sql_create_downloads_table)

            db_conn.execute('PRAGMA user_version = {0}'.format(VERSION))

        if 0 < db_version <= 1:
            # Version 0.10.0
            if execute_sql(db_conn, 'ALTER TABLE downloads ADD COLUMN errors integer DEFAULT 0;'):
                db_conn.execute('PRAGMA user_version = {0}'.format(VERSION))

        if 0 < db_version <= 2:
            # Version 0.12.0
            if execute_sql(db_conn, 'ALTER TABLE mangas ADD COLUMN borders_crop integer;'):
                db_conn.execute('PRAGMA user_version = {0}'.format(VERSION))

        if 0 < db_version <= 3:
            # Version 0.15.0
            execute_sql(db_conn, 'CREATE INDEX idx_chapters_downloaded on chapters(manga_id, downloaded);')
            execute_sql(db_conn, 'CREATE INDEX idx_chapters_recent on chapters(manga_id, recent);')
            execute_sql(db_conn, 'CREATE INDEX idx_chapters_read on chapters(manga_id, read);')
            db_conn.execute('PRAGMA user_version = {0}'.format(VERSION))

        if 0 < db_version <= 4:
            # Version 0.16.0
            if execute_sql(db_conn, 'ALTER TABLE chapters ADD COLUMN scanlators json;'):
                db_conn.execute('PRAGMA user_version = {0}'.format(VERSION))

        if 0 < db_version <= 5:
            # Version 0.22.0
            if execute_sql(db_conn, 'ALTER TABLE mangas RENAME COLUMN reading_direction TO reading_mode;'):
                db_conn.execute('PRAGMA user_version = {0}'.format(VERSION))

        print('DB version', db_conn.execute('PRAGMA user_version').fetchone()[0])

        db_conn.close()


def insert_row(db_conn, table, data):
    try:
        cursor = db_conn.execute(
            'INSERT INTO {0} ({1}) VALUES ({2})'.format(table, ', '.join(data.keys()), ', '.join(['?'] * len(data))),
            tuple(data.values())
        )
        return cursor.lastrowid
    except Exception as e:
        print('SQLite-error:', e, data)
        return None


def insert_rows(db_conn, table, data):
    sql = 'INSERT INTO {0} ({1}) VALUES ({2})'.format(table, ', '.join(data[0].keys()), ', '.join(['?'] * len(data[0])))

    seq = []
    for i in range(len(data)):
        seq.append(tuple(data[i].values()))

    try:
        db_conn.executemany(sql, seq)
        return True
    except Exception as e:
        print('SQLite-error:', e, data)
        return False


def update_row(db_conn, table, id, data):
    try:
        db_conn.execute(
            'UPDATE {0} SET {1} WHERE id = ?'.format(table, ', '.join(k + ' = ?' for k in data)),
            tuple(data.values()) + (id,)
        )
        return True
    except Exception as e:
        print('SQLite-error:', e, data)
        return False


def update_rows(db_conn, table, ids, data):
    sql = 'UPDATE {0} SET {1} WHERE id = ?'.format(table, ', '.join(k + ' = ?' for k in data[0]))

    seq = []
    for i in range(len(ids)):
        seq.append(tuple(data[i].values()) + (ids[i], ))

    try:
        db_conn.executemany(sql, seq)
        return True
    except Exception as e:
        print('SQLite-error:', e, data)
        return False


class Manga:
    _chapters = None
    _server = None

    STATUSES = dict(
        complete=_('Complete'),
        ongoing=_('Ongoing'),
        suspended=_('Suspended'),
        hiatus=_('Hiatus'),
    )

    def __init__(self, server=None):
        if server:
            self._server = server

    @classmethod
    def get(cls, id, server=None):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT * FROM mangas WHERE id = ?', (id,)).fetchone()
        db_conn.close()

        if row is None:
            return None

        manga = cls(server=server)
        for key in row.keys():
            setattr(manga, key, row[key])

        return manga

    @classmethod
    def new(cls, data, server):
        data = data.copy()
        chapters = data.pop('chapters')
        cover_url = data.pop('cover')

        # Fill data with internal data
        data.update(dict(
            last_read=datetime.datetime.now(),
        ))

        # Long strip detection (Webtoon)
        if Settings.get_default().long_strip_detection and server.long_strip_genres and data['genres']:
            for genre in server.long_strip_genres:
                if genre in data['genres']:
                    data.update(dict(
                        reading_mode='webtoon',
                        scaling='width',
                    ))
                    break

        db_conn = create_db_connection()
        with db_conn:
            id = insert_row(db_conn, 'mangas', data)

            if id is not None:
                rank = 0
                for chapter_data in chapters:
                    chapter = Chapter.new(chapter_data, rank, id, db_conn)
                    if chapter is not None:
                        rank += 1

        db_conn.close()

        manga = cls.get(id, server)

        if manga:
            if not os.path.exists(manga.path):
                os.makedirs(manga.path)

            manga._save_cover(cover_url)

            return manga
        return None

    @property
    def chapters(self):
        if self._chapters is None:
            db_conn = create_db_connection()
            if self.sort_order == 'asc':
                rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ? ORDER BY rank ASC', (self.id,))
            else:
                rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ? ORDER BY rank DESC', (self.id,))

            self._chapters = []
            for row in rows:
                self._chapters.append(Chapter(row=row, manga=self))

            db_conn.close()

        return self._chapters

    @property
    def class_name(self):
        return get_server_class_name_by_id(self.server_id)

    @property
    def cover_fs_path(self):
        path = os.path.join(self.path, 'cover.jpg')
        if os.path.exists(path):
            return path

        return None

    @property
    def dir_name(self):
        return get_server_dir_name_by_id(self.server_id)

    @property
    def module_name(self):
        return get_server_module_name_by_id(self.server_id)

    @property
    def nb_downloaded_chapters(self):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT count() AS downloaded FROM chapters WHERE manga_id = ? AND downloaded = 1', (self.id,)).fetchone()
        db_conn.close()

        return row['downloaded']

    @property
    def nb_to_read_chapters(self):
        db_conn = create_db_connection()
        row = db_conn.execute(
            'SELECT count() AS to_read FROM chapters WHERE manga_id = ? AND downloaded = 1 and read = 0', (self.id,)).fetchone()
        db_conn.close()

        return row['to_read']

    @property
    def nb_recent_chapters(self):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT count() AS recents FROM chapters WHERE manga_id = ? AND recent = 1', (self.id,)).fetchone()
        db_conn.close()

        return row['recents']

    @property
    def nb_unread_chapters(self):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT count() AS unread FROM chapters WHERE manga_id = ? AND read = 0', (self.id,)).fetchone()
        db_conn.close()

        return row['unread']

    @property
    def path(self):
        return os.path.join(get_data_dir(), self.dir_name, self.name)

    @property
    def server(self):
        if self._server is None:
            module = importlib.import_module('.' + self.module_name, package='komikku.servers')
            self._server = getattr(module, self.class_name)()

        return self._server

    def _save_cover(self, url):
        if url is None:
            return

        # Save cover image file
        cover_data = self.server.get_manga_cover_image(url)
        if cover_data is None:
            return

        cover_fs_path = os.path.join(self.path, 'cover.jpg')

        with open(cover_fs_path, 'wb') as fp:
            fp.write(cover_data)

    def delete(self):
        db_conn = create_db_connection()

        with db_conn:
            db_conn.execute('DELETE FROM mangas WHERE id = ?', (self.id, ))

        db_conn.close()

        if os.path.exists(self.path):
            shutil.rmtree(self.path)

    def get_next_chapter(self, chapter, direction=1):
        """
        :param chapter: reference chapter
        :param direction: -1 for preceding chapter, 1 for following chapter
        """
        assert direction in (-1, 1), 'Invalid direction value'

        db_conn = create_db_connection()
        if direction == 1:
            row = db_conn.execute(
                'SELECT * FROM chapters WHERE manga_id = ? AND rank > ? ORDER BY rank ASC', (self.id, chapter.rank)).fetchone()
        else:
            row = db_conn.execute(
                'SELECT * FROM chapters WHERE manga_id = ? AND rank < ? ORDER BY rank DESC', (self.id, chapter.rank)).fetchone()
        db_conn.close()

        if not row:
            return None

        return Chapter(row=row, manga=self)

    def update(self, data):
        """
        Updates specific fields

        :param dict data: fields to update
        :return: True on success False otherwise
        """
        ret = False

        # Update
        for key in data:
            setattr(self, key, data[key])

        db_conn = create_db_connection()
        with db_conn:
            ret = update_row(db_conn, 'mangas', self.id, data)

        db_conn.close()

        return ret

    def update_full(self):
        """
        Updates manga

        Fetches and saves data available in manga's HTML page on server

        :return: True on success False otherwise, recent chapters IDs, number of deleted chapters
        :rtype: tuple
        """
        gone_chapters_ranks = []
        recent_chapters_ids = []
        nb_deleted_chapters = 0

        def get_free_rank(rank):
            if rank not in gone_chapters_ranks:
                return rank

            return get_free_rank(rank + 1)

        data = self.server.get_manga_data(dict(slug=self.slug, url=self.url))
        if data is None:
            return False, 0, 0

        db_conn = create_db_connection()
        with db_conn:
            # Update cover
            cover = data.pop('cover')
            if cover:
                self._save_cover(cover)

            # Update chapters
            chapters_data = data.pop('chapters')

            # First, delete chapters that no longer exist on server EXCEPT those marked as downloaded
            # In case of downloaded, we keep track of ranks because they must not be reused
            chapters_slugs = [chapter_data['slug'] for chapter_data in chapters_data]
            rows = db_conn.execute('SELECT * FROM chapters WHERE manga_id = ?', (self.id,))
            for row in rows:
                if row['slug'] not in chapters_slugs:
                    gone_chapter = Chapter.get(row['id'], manga=self, db_conn=db_conn)
                    # Interestingly, Manga Plus chapters remain accessible through the same slugs indefinitely.
                    # So, there's no need to remove the chapter if the server is Manga Plus.
                    if not gone_chapter.downloaded and not self.server.id == 'mangaplus':
                        # Delete chapter
                        gone_chapter.delete(db_conn)
                        nb_deleted_chapters += 1

                        logger.warning(
                            '[UPDATE] {0} ({1}): Delete chapter {2} (no longer available)'.format(
                                self.name, self.server_id, gone_chapter.title
                            )
                        )
                    else:
                        # Keep track of rank freed
                        gone_chapters_ranks.append(gone_chapter.rank)

            # Then, add or update chapters
            rank = 0
            for chapter_data in chapters_data:
                row = db_conn.execute(
                    'SELECT * FROM chapters WHERE manga_id = ? AND slug = ?', (self.id, chapter_data['slug'])
                ).fetchone()

                rank = get_free_rank(rank)
                if row:
                    # Update chapter rank
                    chapter_data['rank'] = rank
                    update_row(db_conn, 'chapters', row['id'], chapter_data)
                    rank += 1
                else:
                    # Add new chapter
                    chapter_data.update(dict(
                        manga_id=self.id,
                        rank=rank,
                        downloaded=0,
                        recent=1,
                        read=0,
                    ))
                    id = insert_row(db_conn, 'chapters', chapter_data)
                    if id is not None:
                        recent_chapters_ids.append(id)
                        rank += 1

                        logger.info('[UPDATE] {0} ({1}): Add new chapter {2}'.format(self.name, self.server_id, chapter_data['title']))

            if len(recent_chapters_ids) > 0 or nb_deleted_chapters > 0:
                data['last_update'] = datetime.datetime.now()

            self._chapters = None

            # Store old path
            old_path = self.path

            # Update
            for key in data:
                setattr(self, key, data[key])

            update_row(db_conn, 'mangas', self.id, data)

            if old_path != self.path:
                # Manga name changes, manga folder must be renamed too
                os.rename(old_path, self.path)

        db_conn.close()

        return True, recent_chapters_ids, nb_deleted_chapters


class Chapter:
    _manga = None

    def __init__(self, row=None, manga=None):
        if row is not None:
            if manga:
                self._manga = manga
            for key in row.keys():
                setattr(self, key, row[key])

    @classmethod
    def get(cls, id, manga=None, db_conn=None):
        if db_conn is not None:
            row = db_conn.execute('SELECT * FROM chapters WHERE id = ?', (id,)).fetchone()
        else:
            db_conn = create_db_connection()
            row = db_conn.execute('SELECT * FROM chapters WHERE id = ?', (id,)).fetchone()
            db_conn.close()

        if row is None:
            return None

        return cls(row, manga)

    @classmethod
    def new(cls, data, rank, manga_id, db_conn=None):
        # Fill data with internal data
        data = data.copy()
        data.update(dict(
            manga_id=manga_id,
            rank=rank,
            downloaded=0,
            recent=0,
            read=0,
        ))

        if db_conn is not None:
            id = insert_row(db_conn, 'chapters', data)
        else:
            db_conn = create_db_connection()

            with db_conn:
                id = insert_row(db_conn, 'chapters', data)

            db_conn.close()

        return cls.get(id, db_conn=db_conn) if id is not None else None

    @property
    def manga(self):
        if self._manga is None:
            self._manga = Manga.get(self.manga_id)

        return self._manga

    @property
    def path(self):
        # BEWARE: self.slug may contain '/' characters
        # os.makedirs() must be used to create chapter's folder
        return os.path.join(self.manga.path, self.slug)

    def delete(self, db_conn=None):
        if db_conn is not None:
            db_conn.execute('DELETE FROM chapters WHERE id = ?', (self.id, ))
        else:
            db_conn = create_db_connection()

            with db_conn:
                db_conn.execute('DELETE FROM chapters WHERE id = ?', (self.id, ))

            db_conn.close()

        if os.path.exists(self.path):
            shutil.rmtree(self.path)

    def get_page(self, page_index):
        if not self.pages:
            return None

        page_path = self.get_page_path(page_index)
        if page_path:
            return page_path

        data = self.manga.server.get_manga_chapter_page_image(self.manga.slug, self.manga.name, self.slug, self.pages[page_index])
        if data is None:
            return None

        if not os.path.exists(self.path):
            os.makedirs(self.path, exist_ok=True)

        image = data['buffer']
        page_path = os.path.join(self.path, data['name'])

        if data['mime_type'] == 'image/webp' or self.scrambled:
            if data['mime_type'] == 'image/webp':
                image = convert_image(image)

            if self.scrambled:
                image = unscramble_image(image)

        if isinstance(image, Image.Image):
            image.save(page_path)
        else:
            with open(page_path, 'wb') as fp:
                fp.write(image)

        updated_data = {}
        if self.pages[page_index]['image'] is None:
            self.pages[page_index]['image'] = data['name']
            updated_data['pages'] = self.pages

        downloaded = len(next(os.walk(self.path))[2]) == len(self.pages)
        if downloaded != self.downloaded:
            updated_data['downloaded'] = downloaded

        if updated_data:
            self.update(updated_data)

        return page_path

    def get_page_path(self, page_index):
        if self.pages and self.pages[page_index]['image'] is not None:
            # self.pages[page_index]['image'] can be an image name or an image url (path + eventually a query string)

            # Extract filename
            imagename = self.pages[page_index]['image'].split('/')[-1]
            # Remove query string
            imagename = imagename.split('?')[0]

            path = os.path.join(self.path, imagename)

            return path if os.path.exists(path) else None

        return None

    def reset(self):
        if os.path.exists(self.path):
            shutil.rmtree(self.path)

        self.update(dict(
            pages=None,
            downloaded=0,
            read=0,
            last_page_read_index=None,
        ))

    def update(self, data):
        """
        Updates specific fields

        :param dict data: fields to update
        :return: True on success False otherwise
        """
        ret = False

        for key in data:
            setattr(self, key, data[key])

        db_conn = create_db_connection()
        with db_conn:
            ret = update_row(db_conn, 'chapters', self.id, data)

        db_conn.close()

        return ret

    def update_full(self):
        """
        Updates chapter

        Fetches server and saves chapter data

        :return: True on success False otherwise
        """
        if self.pages:
            return True

        data = self.manga.server.get_manga_chapter_data(self.manga.slug, self.manga.name, self.slug, self.url)
        if data is None or not data['pages']:
            return False

        return self.update(data)


class Download:
    _chapter = None

    STATUSES = dict(
        pending=_('Download pending'),
        downloaded=_('Downloaded'),
        downloading=_('Downloading'),
        error=_('Download error'),
    )

    @classmethod
    def get(cls, id):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT * FROM downloads WHERE id = ?', (id,)).fetchone()
        db_conn.close()

        if row is None:
            return None

        d = cls()
        for key in row.keys():
            setattr(d, key, row[key])

        return d

    @classmethod
    def get_by_chapter_id(cls, chapter_id):
        db_conn = create_db_connection()
        row = db_conn.execute('SELECT * FROM downloads WHERE chapter_id = ?', (chapter_id,)).fetchone()
        db_conn.close()

        if row:
            d = cls()

            for key in row.keys():
                setattr(d, key, row[key])

            return d

        return None

    @classmethod
    def next(cls, exclude_errors=False):
        db_conn = create_db_connection()
        if exclude_errors:
            row = db_conn.execute('SELECT * FROM downloads WHERE status = "pending" ORDER BY date ASC').fetchone()
        else:
            row = db_conn.execute('SELECT * FROM downloads ORDER BY date ASC').fetchone()
        db_conn.close()

        if row:
            c = cls()

            for key in row.keys():
                setattr(c, key, row[key])

            return c

        return None

    @property
    def chapter(self):
        if self._chapter is None:
            self._chapter = Chapter.get(self.chapter_id)

        return self._chapter

    def delete(self):
        db_conn = create_db_connection()

        with db_conn:
            db_conn.execute('DELETE FROM downloads WHERE id = ?', (self.id, ))

        db_conn.close()

    def update(self, data):
        """
        Updates download

        :param data: percent of pages downloaded, errors or status
        :return: True on success False otherwise
        """

        db_conn = create_db_connection()
        result = False

        with db_conn:
            if update_row(db_conn, 'downloads', self.id, data):
                result = True
                for key in data:
                    setattr(self, key, data[key])

        db_conn.close()

        return result
