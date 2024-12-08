create database blackmetal;

\c blackmetal

create table artists (
    artist_id serial primary key,
    name varchar,
    bio varchar,
    modified timestamp default timezone('utc', now()),
);

create unique index artist_id_name
on artists(artist_id, name);

alter sequence artists_artist_id_seq restart with 100;

create table albums(
    album_id serial primary key,
    title varchar,
    release_year smallint,
    stock smallint check (stock >= 0) default 0,
    price decimal(4,2),
    photo varchar,
    artist_id smallint,
    modified timestamp default timezone('utc', now()),
    foreign key (artist_id) references artists (artist_id)
);

alter table albums add constraint no_negative_stock check (stock >= 0);

alter sequence albums_album_id_seq restart with 1000;

create table users(
    user_id serial primary key,
    role varchar check (role in ('user','admin')),
    username varchar unique,
    password varchar not null,
    created timestamp default timezone('utc', now())
);

create table songs(
    track smallint,
    album_id smallint,
    duration smallint,
    song varchar,
    primary key(track, album_id),
    foreign key (album_id) references albums(album_id) on delete cascade
);


create table orders(
    order_id serial primary key,
    user_id smallint,
    dispatched timestamp default timezone('utc', now()),
    foreign key (user_id) references users(user_id)
);

alter sequence orders_order_id_seq restart with 10000;

create table orders_bridge(
    order_id int,
    album_id smallint,
    quantity smallint,
    primary key(order_id, album_id),
    foreign key (album_id) references albums (album_id),
    foreign key (order_id) references orders (order_id) on delete cascade
);

create table cart(
	user_id smallint,
	album_id smallint,
	quantity smallint,
	primary key (user_id,album_id),
	foreign key (user_id) references users(user_id),
	foreign key (album_id) references albums(album_id)
);

revoke all on schema public from public;
create role bm_admin login password;
grant connect on database blackmetal TO bm_admin;
grant usage on schema public to bm_admin;
grant select, insert, update, delete on all tables in schema public to bm_admin;
grant usage, select on all sequences in schema public to bm_admin;

create function get_album(in id_type varchar, in album_name varchar,in identifier int,out album json, out songs json) 
returns setof record as 
$$
begin
    case id_type
        when 'album_id' then
            return query select json_build_object('album_id',albums.album_id,'artist_id',artists.artist_id,'name',name,
            'title', title, 'release_year',release_year,'photo', photo,'stock',stock,'price',price::float) as album,
            json_agg(json_build_object('track',track,'song',song,'duration',duration) order by track)  as songs
            from albums join artists on artists.artist_id = albums.artist_id
            join songs on songs.album_id = albums.album_id 
            where albums.album_id = $3 
            group by albums.album_id,artists.artist_id,name;
        when 'artist_id' then
            return query select json_build_object('album_id',albums.album_id,'artist_id',artists.artist_id,'name',name,
            'title', title, 'release_year',release_year,'photo', photo,'stock',stock,'price',price::float) as album,
            json_agg(json_build_object('track',track,'song',song,'duration',duration) order by track)  as songs
            from albums join artists on artists.artist_id = albums.artist_id
            join songs on songs.album_id = albums.album_id 
            where artists.artist_id = $3 and lower(title) = $2 
            group by albums.album_id,artists.artist_id,name;
    end case;
end
$$ language plpgsql;

create function get_cart_count(in username varchar, in album_id int, out cart bigint) as
$$
    select coalesce(sum(quantity),0) as cart from cart 
    join users on users.user_id = cart.user_id 
    where users.username = $1 and cart.album_id = $2;
$$ language sql;

create function get_orders_and_cart(in username varchar, out cart json, out orders json) as
$$
    select cart, orders from
    (select json_build_object('balance',sum(cart.quantity * albums.price),
    'albums',json_agg(json_build_object('artist_id',artists.artist_id,
	'photo',albums.photo,'title',albums.title,'artist',artists.name,
	'quantity',cart.quantity,'price',albums.price))) as cart from cart
    join albums on albums.album_id = cart.album_id
    join artists on artists.artist_id = albums.artist_id
    join users on users.user_id = cart.user_id
    where users.username = 'varg_vikernes') as cart,
    (select coalesce(json_agg(orders),'[]') as orders from (select 
    json_build_object('order_id',orders.order_id,'dispatched',orders.dispatched,
    'balance',sum(orders_bridge.quantity * albums.price),'albums',
    json_agg(json_build_object('artist_id',artists.artist_id,'photo',albums.photo,
	'title',albums.title,'artist',artists.name,'quantity',orders_bridge.quantity,
	'price',albums.price))) as orders
    from orders
    join orders_bridge on orders_bridge.order_id = orders.order_id
    join albums on albums.album_id = orders_bridge.album_id
    join artists on artists.artist_id = albums.artist_id
    join users on users.user_id = orders.user_id
    where users.username = 'varg_vikernes'
    group by orders.order_id order by orders.order_id desc) orders ) as orders;
$$ language sql;


create function get_artist(in artist_id int,in view varchar,out artist json) returns setof json as
$$
begin
    case view
        when 'user' then 
            return query select json_build_object('name',artists.name,'bio',artists.bio,
			'albums',json_agg(json_build_object('album_id',albums.album_id,'artist_id',
			artists.artist_id,'title',albums.title,'name',artists.name,'release_year',
			albums.release_year,'photo',albums.photo,'stock',albums.stock,'price',
			albums.price::float))) as artist from albums 
            join artists on artists.artist_id = albums.artist_id 
            where artists.artist_id = $1 group by artists.artist_id;
        when 'admin' then
            return query select json_build_object('artist_id',artists.artist_id,'name', 
            artists.name,'bio', artists.bio ) as artist 
            from artists where artists.artist_id = $1;
    end case;
end
$$ language plpgsql;

create function get_user(in api_username varchar,in task varchar,out bm_user json) 
returns setof json as 
$$
begin
    case task
        when 'owner' then
            return query select json_build_object('user_id',users.user_id) as bm_user 
            from users where users.username=$1;
        when 'password' then
            return query select json_build_object('username',users.username,'password',users.password,
            'created',users.created,'role',users.role) as bm_user
            from users where username = $1;
        when 'cart' then
            return query select json_build_object('username',users.username,'created',users.created,'orders', 
            coalesce(count(distinct(order_id)), 0),'cart',coalesce(count(distinct(album_id)),0)) as bm_user 
            from users 
            left join orders on users.user_id = orders.user_id
            left join cart on cart.user_id = users.user_id where users.username = $1
            group by username,created;
        when 'checkout' then
            return query select json_build_object('user_id',users.user_id,'albums',
            json_agg(json_build_object('album_id',album_id,'quantity',quantity))) as bm_user
            from cart
            join users on users.user_id = cart.user_id
            where users.username = $1
            group by users.user_id;
    end case;
end
$$ language plpgsql;

create function get_pages(in scope varchar, in query varchar default null,out pages int) returns setof int as 
$$
begin
    case scope
        when 'albums' then
            if $2 is null then
                return query select ceil(count(album_id)::float / 8)::int as pages 
                from albums;
            else
                return query select ceil(count(album_id)::float / 8)::int as pages 
                from albums
                join artists on artists.artist_id = albums.artist_id 
                where lower(name) like lower('%' || $2 || '%')  or lower(title) like lower('%' || $2 || '%') ;
            end if;
        when 'artists' then
            if $2 is null then
                return query select ceil(count(artist_id)::float / 8)::int as pages 
                from artists;
            else
                return query select ceil(count(artist_id)::float / 8)::int as pages 
                from artists where lower(name) like lower('%' || $2 || '%');
            end if;
    end case;
end
$$ language plpgsql;


create function create_artist(in name varchar, in bio varchar,out name varchar,out artist_id int) as
$$
    insert into artists (name,bio) values ($1,$2) returning name,artist_id;
$$ language sql;


create or replace function get_artists(in page int default null,in sort varchar default null,in direction varchar default null,in query varchar default null,out artists json)
returns setof json as 
$$
declare 
has_params boolean := false = all(select unnest(array[$1::varchar,$2,$3]) is null);
new_offset smallint := ($1 - 1) * 8;
new_query varchar := ' where lower(name) like lower(''%' || $4 || '%'') ';
begin  
	if has_params then
    return query execute
        'select json_agg(
	        json_build_object(''artist_id'',s.artist_id,''name'',s.name,
		        ''bio'',s.bio,''modified'',s.modified,''albums'',s.albums)) as artists
        from (select 
		        artists.artist_id,
		        artists.name,artists.bio,
		        artists.modified::varchar,
		        count(album_id) as albums 
	        from artists left join albums on 
	        albums.artist_id = artists.artist_id'
            || case when $4 is not null then new_query else ' ' end ||  
	        'group by artists.artist_id order by'
            || case $3 when 'ascending' then format(' %s asc ',$2) when 'descending' then format(' %s desc ',$2) end || 
            format('limit 8 offset %s',new_offset) || ') as s'; 
	else
		return query execute
		'select json_agg(json_build_object(''name'',name,''artist_id'',artist_id)order by name asc) as artists from artists;';			 
	end if;
end
$$ language plpgsql;

create function get_albums(in page int,in sort varchar,in direction varchar,in query varchar default null)
returns table (
    artist_id smallint,
    photo varchar,
    title varchar,
    name varchar, 
	stock smallint, 
    release_year smallint, 
    price double precision,
    modified varchar
) as 
$$
declare 
new_offset smallint := ($1 - 1) * 8;
new_query varchar := ' where lower(name) like lower(''%' || $4 || '%'') or lower(title) like lower(''%' || $4 || '%'')';
begin  
    return query execute '
    select albums.artist_id,albums.photo,albums.title,artists.name,albums.stock,
    albums.release_year,albums.price::float, albums.modified::varchar
    from albums
    join artists on artists.artist_id = albums.artist_id'
    || case when $4 is not null then new_query else ' ' end || 
    'order by'
    || case $3 when 'ascending' then format(' %s asc ',$2) when 'descending' then format(' %s desc ',$2) end || 
    format('limit 8 offset %s',new_offset); 
end
$$ language plpgsql;

create function update_songs(in existing_tracks int[],in existing_album_ids int[],
    in new_durations int[],in new_songs varchar[])
returns void as 
$$
    update albums 
    set song = new_songs.song,
    	duration = new_songs.duration
    from (select 
		unnest($1) as track,
		unnest($2) as album_id,
		unnest($3) as duration,
		unnest($4) as song ) as new_songs
    where new_songs.album_id=songs.album_id
    and new_songs.track=songs.track;
$$ language sql;


create function update_photos(in existing_album_ids int[],in photos varchar[])
returns void as 
$$
    update albums 
    set photo = new_photos.photo,
    	modified = now() at time zone 'utc'
    from (select 
		unnest($1) as album_id,
		unnest($2) as photo) as new_photos
    where new_photos.album_id=albums.album_id;
$$ language sql;


create function insert_songs(in tracks_ids int[],in album_ids int[],
    in durations int[],in new_songs varchar[]) 
returns void as
$$
    insert into songs (track,album_id,duration,song)
    select  unnest($1), unnest($2),unnest($3),unnest($4);
$$ language sql;


create function delete_songs(in album_id int, in del_songs int[]) 
returns void as
$$
    delete from songs where album_id = $1
    and track in (select unnest($2));
$$ language sql;

create function create_user(in username varchar, in password varchar, in role varchar) 
returns void as
$$
    insert into users (username,password,role) values ($1,$2,$3);
$$ language sql;

create function create_order(in user_id int,out order_id int) as
$$
    insert into orders (user_id) values ($1) returning order_id;
$$ language sql;

create function create_dispatch_items(in order_id int, in album_ids int[], in quantities int[]) 
returns void as
$$
    insert into orders_bridge (order_id,album_id,quantity)
    select  $1, unnest($2),unnest($3);
$$ language sql;

create function remove_cart_items(in user_id int,in album_id int default null) 
returns void as
$$
begin
    if $2 is null then
        delete from cart where cart.user_id = $1;
    else
        delete from cart where cart.user_id = $1 and cart.album_id = $2;
    end if;
end
$$ language plpgsql;

create function check_cart_item(in user_id int,in album_id int,out in_cart int) as
$$
    select count(cart.album_id) as in_cart
    from cart where cart.user_id = $1 and cart.album_id=$2;
$$ language sql;

create function add_cart_item(in user_id int,in album_id int) 
returns void as
$$
    insert into cart (user_id,album_id,quantity) values ($1, $2, 1); 
$$ language sql;

create function update_cart_quantity(in user_id int,in album_id int,in amount int) 
returns void as
$$
    update cart set quantity = quantity + $3
    where cart.user_id = $1 and cart.album_id = $2;
$$ language sql;

create function update_stock_quantity(in user_id int,in album_id int,in amount int,out remaining int, out cart int) as
$$
    update albums set stock = albums.stock + $3 from 
    (select albums.album_id,albums.stock,cart.quantity 
    from cart join albums on albums.album_id = cart.album_id 
    where cart.user_id = $1 and albums.album_id = $2) as sub 
    where sub.album_id = albums.album_id returning albums.stock as remaining, sub.quantity as cart;
$$ language sql;

create function update_modified(in album_id int,out artist_id int,out title varchar) as
$$  
    with updated as (
    update albums set modified = now() at time zone 'utc'
    where album_id = $1 returning *)
    select artists.artist_id,title from updated join artists on artists.artist_id = updated.artist_id;
$$ language sql;

create function insert_album(in title varchar,in release_year int,in price double precision,
    in photo varchar,in artist_id int,out album_id int,out artist_id int,out title varchar) 
as
$$
    with inserted as 
    (insert into albums (title,release_year,price,photo,artist_id) 
    values ($1,$2,$3,$4,$5) returning *) 
    select album_id,artists.artist_id,title
    from inserted join artists on artists.artist_id = inserted.artist_id;
$$ language sql;

create function update_artist(in api_artist_id int,in api_name varchar,in bio varchar) 
returns table (
    artist_id int,
    name varchar
) as 
$$
declare
    set_name varchar:= ' name = '''||$2||'''';
    set_bio varchar:= ' bio = '''||$3||'''';
    set_modified varchar:= ' modified = now() at time zone ''utc''';
    sets varchar[] := array[set_name,set_bio,set_modified];
begin
    return query execute 'update artists set '||array_to_string(sets, ',')||' where artist_id='||$1||' returning artist_id,name;';
end
$$ language plpgsql;

create function update_album(in album_id int,in title varchar,in release_year int,
    in price double precision,in artist_id int,in photo varchar) 
    returns void as 
$$
declare 
	set_title varchar:= ' title = '''||$2||'''';
	set_release_year varchar:= ' release_year = '||$3||'';
	set_price varchar:= ' price = '||$4||'';
	set_artist_id varchar:= ' artist_id = '||$5||'';
	set_photo varchar:= ' photo = '''||$6||'''';
	set_modified varchar:= ' modified = now() at time zone ''utc''';
    sets varchar[] := array[set_title,set_release_year,set_price,set_photo,set_artist_id,set_modified];
begin  
	execute 'update albums set '||array_to_string(sets, ',')||' where album_id='||$1||';';
end
$$ language plpgsql;

insert into artists (artist_id, name, bio) values
(100,'Ascension','Black metal band from Tornau vor der Heide, Saxony-Anhalt, Germany.'),
(101,'The Black','Black metal band from Sweden.

The band was formed in 1991 as "The Black Flame", after recording the first demo tape they shortened their name to "The Black".'),
(102,'Corpus Christii','Nocturnus Horrendus is the owner of Nightmare Productions.

The band''s first demo had the band''s name spelled Corpus Christi. All subsequent releases have spelled it Corpus Christii with a second "i".'),
(103,'Imperium Dekadenz','Imperium Dekadenz was founded during late summer 2004 by Vespasian and Horaz.

The band was featured on the In Autumnal Fog 2009 sampler with the song "An Autumn Serenade", freely downloadable on the Autumnal Fog website.'),
(104,'Kataxu','Symphonic Black Metal band from Poland, formed in 1994.'),
(105,'Krohm','Black Metal solo project formed in 1995 in the United States.'),
(106,'Warmoon Lord','The band''s name is taken from the song Warmoon Lord by Vlad Tepes.'),
(107,'Azarath','Inferno is the only remaining founding member.
The name Azarath was taken from the title of Damnation song called "Azarath (Watching in Darkness)".'),
(108,'Deströyer 666','Started out in May 1994 as a solo-project of K.K. Warslut. In 2001, the band relocated to the South Holland, Netherlands. In 2003, Simon Berserker decided to return to Australia and left the band, while Shrapnel''s Dutch visa expired and he had to relocate again to London.'),
(109,'Mayhem','The band was billed as Wolf''s Lair Abyss for a few secret gigs during the Wolf''s Lair Abyss tour.

Founded by Jørn Stubberud (Necrobutcher), and Kjetil (Manheim) under the name Musta (Finnish for "black"), which they changed to Mayhem after Øystein Aarseth (Euronymous) joined in. The band name is taken from ...'),
(110,'Deus Mortem','Deus Mortem - a Polish black metal band. It was established at the end of 2008 in Wrocław on the initiative of the guitarist and vocalist Marek "Necrosodoma" Lechowski, known, among others, from performances in the groups Anima Damnata and Thunderbolt.'),
(111,'Walknut','Walknut is a Russian Atmospheric black metal band from Moscow, formed in 2006. The members of the band are Stringsskald and Ravnaskrik.'),
(112,'Sielunvihollinen','The band''s name literally translates to "the enemy of the soul", but in Finnish means "the devil".'),
(113,'Abigor','Abigor is an Austrian black metal band formed in 1993. They are named after an upper demon of war in Christian demonology.'),
(114,'Dissection','The band''s first song ever written was "Inhumanity Deformed", a Napalm Death-inspired grindcore piece, but soon they developed their own melancholic and atmospheric style of death metal.

The band first disbanded due to Jon Nödtveidt''s accomplice to a murder conviction. He was serving time in prison from 1997 until early 2004 and then reactivated the band.

Jon Nödtveidt (aged 31) shot and killed himself on August 13th, 2006. Swedish police found him in his apartment inside a circle of lit candles. It is believed that he killed himself because he felt he had achieved all that he could/was meant to in this life. According to some who knew him, this was probably planned ever since he got out of jail.'),
(115,'Nokturnal Mortum','"Nocturnal" was changed to "Nokturnal" to avoid any possible confusion with other bands.

As of 2014, the band has claimed to have distanced themselves from the racist/political themes of their earlier lyrics, though since then they''ve still continued to play at NSBM shows.'),
(116,'Necrophobic','Formed in 1989 by Blackmoon and Joakim Sterner to create a darker kind of death metal than what was being made at the time. The name was taken from a Slayer song.');

insert into albums (artist_id, album_id, title, release_year, stock, price, photo) values
(100,1000,'The Dead of the World',2014,5,9.27,'ascension-the-dead-of-the-world-Cover-Art.webp'),
(101,1001,'Alongside Death',2008,0,8.46,'the-black-alongside-death-Cover-Art.webp'),
(102,1002,'Rising',2007,2,9.33,'corpus-christii-rising-Cover-Art.webp'),
(103,1003,'Procella Vadens',2010,5,15.95,'imperium-dekadenz-procella-vadens-Cover-Art.webp'),
(104,1004,'Hunger of Elements',2005,3,17.66,'kataxu-hunger-of-elements-Cover-Art.webp'),
(105,1005,'The Haunting Presence',2007,3,12.69,'krohm-the-haunting-presence-Cover-Art.webp'),
(106,1006,'Battlespells',2021,1,18.17,'warmoon-lord-battlespells-Cover-Art.webp'),
(107,1007,'Blasphemers'' Maledictions',2011,3,16.75,'azarath-blasphemers-maledictions-Cover-Art.webp'),
(108,1008,'Defiance',2009,6,15.97,'destroyer-666-defiance-Cover-Art.webp'),
(109,1009,'De mysteriis dom Sathanas',1994,6,19.25,'mayhem-de-mysteriis-dom-sathanas-Cover-Art.webp'),
(110,1010,'Emanations of the Black Light',2013,6,19.76,'deus-mortem-emanations-of-the-black-light-Cover-Art.webp'),
(111,1011,'Graveforests and Their Shadows',2007,0,17.38,'walknut-graveforests-and-their-shadows-Cover-Art.webp'),
(110,1012,'Kosmocide',2019,0,14.98,'deus-mortem-kosmocide-Cover-Art.webp'),
(112,1013,'Kuolonkylväjä',2019,8,15.88,'sielunvihollinen-kuolonkylvaja-Cover-Art.webp'),
(113,1014,'Nachthymnen (From the Twilight Kingdom)',1995,1,18.34,'abigor-nachthymnen-from-the-twilight-kingdom-Cover-Art.webp'),
(114,1015,'Storm of the Light''s Bane',1995,9,16.78,'dissection-storm-of-the-lights-bane-Cover-Art.webp'),
(110,1016,'The Fiery Blood',2020,0,19.3,'deus-mortem-the-fiery-blood-Cover-Art.webp'),
(114,1017,'The Somberlain',1993,8,12.82,'dissection-the-somberlain-Cover-Art.webp'),
(115,1018,'Голос сталі',2009,3,8.19,'nokturnal-mortum-голос-сталі-Cover-Art.webp'),
(115,1019,'До лунарної поезії (To Lunar Poetry)',2022,0,18.58,'nokturnal-mortum-до-лунарної-поезії-to-lunar-poetry-Cover-Art.webp'),
(116,1020,'Darkside',1997,3,8.39,'necrophobic-darkside-Cover-Art.webp'),
(115,1021,'Goat Horns',1997,4,8.95,'nokturnal-mortum-goat-horns-Cover-Art.webp');

insert into songs (track,album_id,duration,song) values
(1,1000,NULL,'The Silence of Abel'),
(2,1000,NULL,'Death''s Golden Temple'),
(3,1000,NULL,'Black Ember'),
(4,1000,NULL,'Unlocking Tiamat'),
(5,1000,NULL,'Deathless Light'),
(6,1000,NULL,'The Dark Tomb Shines'),
(7,1000,NULL,'Mortui Mundi'),
(1,1001,NULL,'On the Descent to Hell'),
(2,1001,NULL,'Death''s Crown'),
(3,1001,NULL,'A Contract Written in Ashes'),
(4,1001,NULL,'Dead Seed'),
(5,1001,NULL,'Fleshless'),
(6,1001,NULL,'Death Throes'),
(7,1001,NULL,'The Wrath From Beneath'),
(8,1001,NULL,'Alongside Death'),
(1,1002,104.0,'Intro'),
(2,1002,272.0,'Stabbed'),
(3,1002,245.0,'Blank Code'),
(4,1002,264.0,'Black Gleam Eye'),
(5,1002,370.0,'The Wanderer'),
(6,1002,349.0,'Torrents of Sorrow'),
(7,1002,305.0,'Void Revelation'),
(8,1002,238.0,'Evasive Contempt'),
(9,1002,365.0,'Heavenless Bliss'),
(10,1002,201.0,'Untouchable Euphoria'),
(11,1002,259.0,'Bleak Existence'),
(12,1002,391.0,'Revealed Wounds'),
(13,1002,101.0,'Outro'),
(1,1003,121.0,'Die Hoffnung stirbt...'),
(2,1003,301.0,'Lacrimae Mundi'),
(3,1003,625.0,'A Million Moons'),
(4,1003,293.0,'Ego Universalis'),
(5,1003,318.0,'À la nuit tombante'),
(6,1003,558.0,'An Autumn Serenade'),
(7,1003,426.0,'Ocean, Mountain''s Mirror'),
(8,1003,271.0,'The Descent Into Hades'),
(9,1003,405.0,'Procella Vadens'),
(10,1003,118.0,'...wenn der Sturm beginnt'),
(1,1004,813.0,'In My Dungeon!'),
(2,1004,234.0,'In the Arms of the Astral World'),
(3,1004,651.0,'Below the Tree of Life'),
(4,1004,383.0,'Nightsky'),
(5,1004,688.0,'The Manifesto of Unity'),
(6,1004,138.0,'The Breathe of Atlantis'),
(1,1005,443.0,'Bleak Shores'),
(2,1005,575.0,'Lifeless Serenade'),
(3,1005,433.0,'I respiri delle ombre'),
(4,1005,464.0,'Relic'),
(5,1005,495.0,'Memories of the Flesh'),
(6,1005,426.0,'Tra la carne e il nulla'),
(7,1005,547.0,'Syndrome'),
(1,1006,151.0,'Virtus tenebris'),
(2,1006,274.0,'Purging Nefarious Vortex'),
(3,1006,310.0,'Of a Moribund Vision'),
(4,1006,415.0,'The Key of the Moonpiercer'),
(5,1006,398.0,'Empowered With Battlespells'),
(6,1006,284.0,'Oracles of War'),
(7,1006,485.0,'In Perennial Twilight'),
(1,1007,4.0,'Arising the Black Flame'),
(2,1007,238.0,'Supreme Reign of Tiamat'),
(3,1007,240.0,'Crushing Hammer of the Antichrist'),
(4,1007,255.0,'Firebreath of Blasphemy and Scorn'),
(5,1007,226.0,'Behold the Satan''s Sword'),
(6,1007,373.0,'Under the Will of the Lord'),
(7,1007,264.0,'The Abjection'),
(8,1007,268.0,'Deathstorms Raid the Earth'),
(9,1007,218.0,'Lucifer''s Rising'),
(10,1007,256.0,'Holy Possession'),
(11,1007,367.0,'Harvester of Flames'),
(1,1008,183.0,'Weapons of Conquest'),
(2,1008,277.0,'I Am Not Deceived'),
(3,1008,314.0,'Blood for Blood'),
(4,1008,218.0,'The Barricades Are Breaking'),
(5,1008,286.0,'Stand Defiant'),
(6,1008,277.0,'Path to Conflict'),
(7,1008,264.0,'A Thousand Plagues'),
(8,1008,364.0,'Human All Too Human'),
(9,1008,304.0,'Sermon to the Dead'),
(1,1009,347.0,'Funeral Fog'),
(2,1009,383.0,'Freezing Moon'),
(3,1009,310.0,'Cursed in Eternity'),
(4,1009,381.0,'Pagan Fears'),
(5,1009,417.0,'Life Eternal'),
(6,1009,326.0,'From the Dark Past'),
(7,1009,214.0,'Buried by Time and Dust'),
(8,1009,382.0,'De mysteriis dom Sathanas'),
(1,1010,388.0,'Into the Forms of Flesh (The Rebirth)'),
(2,1010,406.0,'It Starts to Breathe Inside'),
(3,1010,266.0,'Receiving the Impurity of Jeh'),
(4,1010,386.0,'The Shining'),
(5,1010,325.0,'The Harvest'),
(6,1010,1102.0,'Ceremony of Reversion P.'),
(7,1010,354.0,'Emanation'),
(1,1011,70.0,'Hrimfaxi'),
(2,1011,631.0,'Motherland Ostenvegr'),
(3,1011,655.0,'Come, Dreadful Ygg'),
(4,1011,270.0,'The Midnightforest of the Runes'),
(5,1011,703.0,'Grim Woods'),
(6,1011,241.0,'Skinfaxi'),
(1,1012,324.0,'Remorseless Beast'),
(2,1012,345.0,'The Soul of the Worlds'),
(3,1012,331.0,'Sinister Lava'),
(4,1012,257.0,'Through the Crown It Departs'),
(5,1012,394.0,'The Seeker'),
(6,1012,1719.0,'Ceremony of Reversion p.'),
(7,1012,397.0,'The Destroyer'),
(1,1013,222.0,'Loputon viha'),
(2,1013,235.0,'Tuhkanharmaa'),
(3,1013,299.0,'Uusi kurja maailma'),
(4,1013,269.0,'Rapistuneen linnan varjot'),
(5,1013,289.0,'Auringon hylkäämä maa'),
(6,1013,230.0,'Voittomme'),
(7,1013,251.0,'Kirous viimeinen'),
(8,1013,281.0,'Kuolonkylväjä'),
(1,1014,384.0,'Unleashed Axe-Age'),
(2,1014,374.0,'Scars in the Landscape of God'),
(3,1014,364.0,'Reborn Through the Gates of Three Moons'),
(4,1014,277.0,'Dornen'),
(5,1014,236.0,'As Astral Images Darken Reality'),
(6,1014,346.0,'The Dark Kiss'),
(7,1014,275.0,'I Face the Eternal Winter'),
(8,1014,322.0,'Revealed Secrets of the Whispering Moon'),
(9,1014,363.0,'A Frozen Soul in a Wintershadow'),
(1,1015,116.0,'At the Fathomless Depths'),
(2,1015,400.0,'Night''s Blood'),
(3,1015,448.0,'Unhallowed'),
(4,1015,351.0,'Where Dead Angels Lie'),
(5,1015,290.0,'Retribution - Storm of the Light''s Bane'),
(6,1015,486.0,'Thorns of Crimson Death'),
(7,1015,416.0,'Soulreaper'),
(8,1015,86.0,'No Dreams Breed in Breathless Sleep'),
(1,1016,249.0,'Down the Scorched Paradise'),
(2,1016,332.0,'Lord of All Graves'),
(3,1016,280.0,'Breaking the Sceptres, Crushing the Wands'),
(4,1016,329.0,'Nod'),
(1,1017,490.0,'Black Horizons'),
(2,1017,424.0,'The Somberlain'),
(3,1017,47.0,'Crimson Towers'),
(4,1017,398.0,'A Land Forlorn'),
(5,1017,283.0,'Heaven''s Damnation'),
(6,1017,225.0,'Frozen'),
(7,1017,64.0,'Into Infinite Obscurity'),
(8,1017,259.0,'In the Cold Winds of Nowhere'),
(9,1017,190.0,'The Grief Prophecy / Shadows Over a Lost Kingdom'),
(10,1017,273.0,'Mistress of the Bleeding Sorrow'),
(11,1017,43.0,'Feathers Fell'),
(1,1018,186.0,'Інтро'),
(2,1018,595.0,'Голос сталі'),
(3,1018,648.0,'Валькирия'),
(4,1018,504.0,'Україна'),
(5,1018,708.0,'Моєї мрії острови'),
(6,1018,547.0,'Шляхом сонця'),
(7,1018,291.0,'Небо сумних ночей'),
(8,1018,708.0,'Біла вежа'),
(1,1019,153.0,'Зимні сни / Freezing Dreams'),
(2,1019,280.0,'Лунарна поезія / Lunar Poetry'),
(3,1019,441.0,'Перунове срібло небес / Perun''s Celestial Silver'),
(4,1019,279.0,'Карпатські таємниці / Carpathian Mysteries'),
(5,1019,289.0,'…І зима постає / …And Winter Becomes'),
(6,1019,644.0,'Вампірів князь прийшов / Return of the Vampire Lord'),
(7,1019,311.0,'Прадавній рід / Ancient Nation'),
(8,1019,268.0,'Акт віри (Ода інакомисленню) / Autodafe (Ode to Nonconformity)'),
(9,1019,232.0,'Пращурів сни / Barbarian Dreams'),
(1,1020,173.0,'Black Moon Rising'),
(2,1020,203.0,'Spawned by Evil'),
(3,1020,220.0,'Bloodthirst'),
(4,1020,84.0,'Venaesectio'),
(5,1020,237.0,'Darkside'),
(6,1020,207.0,'The Call'),
(7,1020,82.0,'Descension'),
(8,1020,163.0,'Nailing the Holy One'),
(9,1020,254.0,'Nifelhel'),
(10,1020,375.0,'Christian Slaughter'),
(1,1021,288.0,'Black Moon Overture'),
(2,1021,424.0,'Kuyaviya'),
(3,1021,547.0,'Goat Horns'),
(4,1021,489.0,'Unholy Orathania'),
(5,1021,708.0,'Veles Scrolls'),
(6,1021,430.0,'Kolyada'),
(7,1021,232.0,'Eternal Circle');