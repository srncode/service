import secrets
import tempfile
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

import qrcode
import streamlit as st
import streamlit.components.v1 as components
from supabase import create_client, Client

import smtplib
from email.message import EmailMessage


# =========================================================
# 기본 설정
# =========================================================

st.set_page_config(page_title="배송 확인 시스템")

KST = timezone(timedelta(hours=9))

DRIVERS = {
    "D001": {"name": "김기사"},
    "D002": {"name": "이기사"},
}

DRIVER_SESSION_HOURS = 8
START_HOURS = 3

EXPIRE_MINUTES = {
    "5분": 5,
    "30분": 30,
    "1시간": 60,
    "6시간": 360,
    "12시간": 720,
    "24시간": 1440,
    "48시간": 2880,
}


# =========================================================
# Supabase 연결
# =========================================================

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]

    return create_client(url, key)


supabase = get_supabase()


# =========================================================
# QR 스캐너
# =========================================================

SCANNER_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<style>
html,body{
    margin:0;
    padding:0;
    background:#000;
    color:#fff;
    font-family:sans-serif;
}

#wrap{
    position:relative;
    width:100%;
    max-width:460px;
    aspect-ratio:1/1;
    margin:0 auto;
    background:#000;
    overflow:hidden;
}

video{
    width:100%;
    height:100%;
    object-fit:cover;
    display:block;
}

.c{
    position:absolute;
    width:46px;
    height:46px;
    border:0 solid #fff;
}

.tl{
    top:14px;
    left:14px;
    border-top-width:6px;
    border-left-width:6px;
}

.tr{
    top:14px;
    right:14px;
    border-top-width:6px;
    border-right-width:6px;
}

.bl{
    bottom:14px;
    left:14px;
    border-bottom-width:6px;
    border-left-width:6px;
}

.br{
    bottom:14px;
    right:14px;
    border-bottom-width:6px;
    border-right-width:6px;
}

#line{
    position:absolute;
    left:8%;
    right:8%;
    height:2px;
    background:rgba(255,80,80,.85);
    top:10%;
    animation:scan 2.2s linear infinite alternate;
}

@keyframes scan{
    from{top:10%}
    to{top:88%}
}

#msg{
    text-align:center;
    padding:10px 6px;
    font-size:14px;
    color:#ccc;
}
</style>
</head>

<body>

<div id="wrap">

    <video id="v" playsinline muted autoplay></video>

    <div class="c tl"></div>
    <div class="c tr"></div>
    <div class="c bl"></div>
    <div class="c br"></div>

    <div id="line"></div>

</div>

<div id="msg">
카메라를 시작하는 중...
</div>

<script src="https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js"></script>

<script>

const video = document.getElementById("v");
const msg = document.getElementById("msg");

const canvas = document.createElement("canvas");
const ctx = canvas.getContext(
    "2d",
    { willReadFrequently: true }
);

let last = {
    text: "",
    t: 0
};


function send(type, data) {

    window.parent.postMessage(
        Object.assign(
            {
                isStreamlitMessage:true,
                type:type
            },
            data || {}
        ),
        "*"
    );

}


function resize(){

    send(
        "streamlit:setFrameHeight",
        {
            height:document.body.scrollHeight
        }
    );

}


function tick(){

    if(
        video.readyState < 2 ||
        !video.videoWidth ||
        typeof jsQR === "undefined"
    ){
        return;
    }

    const scale =
        Math.min(1, 720 / video.videoWidth);

    const w =
        Math.round(video.videoWidth * scale);

    const h =
        Math.round(video.videoHeight * scale);

    canvas.width = w;
    canvas.height = h;

    ctx.drawImage(
        video,
        0,
        0,
        w,
        h
    );

    const img =
        ctx.getImageData(
            0,
            0,
            w,
            h
        );

    const code =
        jsQR(
            img.data,
            w,
            h,
            {
                inversionAttempts:"attemptBoth"
            }
        );

    if(code && code.data){

        const now = Date.now();

        if(
            code.data !== last.text ||
            now - last.t > 3000
        ){

            last = {
                text:code.data,
                t:now
            };

            send(
                "streamlit:setComponentValue",
                {
                    value:{
                        text:code.data,
                        ts:now
                    },
                    dataType:"json"
                }
            );

        }

    }

}


async function start(){

    try{

        const stream =
            await navigator.mediaDevices.getUserMedia({

                video:{
                    facingMode:{
                        ideal:"environment"
                    },

                    width:{
                        ideal:1280
                    },

                    height:{
                        ideal:720
                    }
                },

                audio:false

            });

        video.srcObject = stream;

        await video.play();

        msg.textContent =
            "QR코드를 프레임 안에 맞춰주세요";

        setInterval(
            tick,
            120
        );

    }
    catch(e){

        msg.textContent =
            "카메라를 시작할 수 없습니다. 카메라 권한을 허용해주세요.";

    }

    resize();

}


send(
    "streamlit:componentReady",
    {
        apiVersion:1
    }
);

window.addEventListener(
    "resize",
    resize
);

resize();

start();

</script>

</body>
</html>
"""


_scanner_dir = (
    Path(tempfile.gettempdir())
    / "qr_scanner_component"
)

_scanner_dir.mkdir(
    exist_ok=True
)

(
    _scanner_dir / "index.html"
).write_text(
    SCANNER_HTML,
    encoding="utf-8"
)

qr_scanner = components.declare_component(
    "qr_scanner",
    path=str(_scanner_dir)
)


# =========================================================
# 공통 함수
# =========================================================

def go(page):
    st.session_state.page = page
    st.rerun()


def now_kst():
    return datetime.now(KST)


def iso_now():
    return now_kst().isoformat()


def parse_dt(value):
    if not value:
        return None

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)

    return dt


# =========================================================
# DB 함수
# =========================================================

def db_get_order(order_id):

    result = (
        supabase
        .table("orders")
        .select("*")
        .eq("order_id", order_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    return result.data[0]


def db_get_all_orders():

    result = (
        supabase
        .table("orders")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


def db_insert_order(order):

    result = (
        supabase
        .table("orders")
        .insert(order)
        .execute()
    )

    if not result.data:
        raise Exception("주문 저장에 실패했습니다.")

    return result.data[0]


def db_update_order(order_id, updates):

    result = (
        supabase
        .table("orders")
        .update(updates)
        .eq("order_id", order_id)
        .execute()
    )

    if not result.data:
        raise Exception("주문 수정에 실패했습니다.")

    return result.data[0]


# =========================================================
# 주문 상태
# =========================================================

def expired(order):

    expires_at = order.get("expires_at")

    if not expires_at:
        return False

    dt = parse_dt(expires_at)

    if not dt:
        return False

    return now_kst() >= dt


def status_of(order):

    status = order.get("status", "")
    started = order.get("started_at")

    if status == "배송 시작" and started:

        elapsed = (
            now_kst()
            - parse_dt(started)
        )

        if elapsed >= timedelta(
            hours=START_HOURS
        ):
            return "배송중"

    return status


def fmt_minutes(total):

    days, rest = divmod(
        total,
        1440
    )

    hours, minutes = divmod(
        rest,
        60
    )

    parts = []

    if days:
        parts.append(
            f"{days}일"
        )

    if hours:
        parts.append(
            f"{hours}시간"
        )

    if minutes:
        parts.append(
            f"{minutes}분"
        )

    return " ".join(parts)


def remaining(order):

    expires_at = order.get("expires_at")

    if not expires_at:

        if order.get("expire_minutes"):

            return (
                "배송 완료 후 "
                + fmt_minutes(
                    int(order["expire_minutes"])
                )
                + " 동안 공개"
            )

        return None

    seconds = int(
        (
            parse_dt(expires_at)
            - now_kst()
        ).total_seconds()
    )

    if seconds <= 0:
        return "만료되었습니다."

    days, seconds = divmod(
        seconds,
        86400
    )

    hours, seconds = divmod(
        seconds,
        3600
    )

    minutes, seconds = divmod(
        seconds,
        60
    )

    if days:
        return (
            f"{days}일 "
            f"{hours}시간 "
            f"{minutes}분"
        )

    if hours:
        return (
            f"{hours}시간 "
            f"{minutes}분"
        )

    return (
        f"{minutes}분 "
        f"{seconds}초"
    )


# =========================================================
# QR
# =========================================================

def make_qr(data):

    qr = qrcode.make(data)

    buffer = BytesIO()

    qr.save(
        buffer,
        format="PNG"
    )

    return buffer.getvalue()


def build_qr_text(order_id, order):

    return (
        f"주문번호: {order_id}\n"
        f"구매자: {order['buyer']}\n"
        f"주소: {order['address']}\n"
        f"물품: {order.get('product', '')}\n"
        f"수량: {order.get('quantity', '')}\n"
        f"인증코드: {order.get('token', '')}"
    )


def parse_qr_text(text):

    data = {}

    for line in text.splitlines():

        if ":" in line:

            k, v = line.split(
                ":",
                1
            )

            data[k.strip()] = v.strip()

    return data


def verify_parcel(text, my_oid):

    data = parse_qr_text(text)

    order = db_get_order(my_oid)

    if not order:
        return False

    if (
        data.get("주문번호", "").upper()
        != my_oid
    ):
        return False

    if (
        data.get("구매자")
        != order["buyer"]
    ):
        return False

    if (
        data.get("주소")
        != order["address"]
    ):
        return False

    if (
        data.get("물품")
        != order.get("product", "")
    ):
        return False

    if (
        data.get("수량")
        != str(order.get("quantity", ""))
    ):
        return False

    if (
        order.get("token")
        and data.get("인증코드")
        != order["token"]
    ):
        return False

    return True


# =========================================================
# 화면 함수
# =========================================================

def show_extra(order):

    if "product" in order:

        st.write(
            "**구매 물품:**",
            order["product"]
        )

    if "quantity" in order:

        st.write(
            "**수량:**",
            f'{order["quantity"]}개'
        )

    if "price" in order:

        st.write(
            "**가격:**",
            f'{order["price"]:,}원'
        )

    time_left = remaining(order)

    if time_left:

        st.write(
            "**남은 정보 공개시간:**",
            time_left
        )


def show_expired():

    st.error(
        "정보 열람 가능 시간이 만료되었습니다."
    )

    st.warning(
        "개인정보 보호를 위해 "
        "주문 상세정보가 비공개 처리되었습니다."
    )


# =========================================================
# 배송기사 세션
# =========================================================

@st.cache_resource
def load_driver_sessions():

    return {}


DRIVER_SESSIONS = load_driver_sessions()


def create_driver_session(driver_id):

    token = secrets.token_urlsafe(16)

    DRIVER_SESSIONS[token] = {

        "driver_id": driver_id,

        "expires_at": (
            now_kst()
            + timedelta(
                hours=DRIVER_SESSION_HOURS
            )
        ).isoformat()

    }

    st.session_state.driver_token = token
    st.session_state.driver_id = driver_id
    st.session_state.driver = DRIVERS[driver_id]

    st.query_params["dt"] = token


def end_driver_session():

    token = (
        st.session_state.get(
            "driver_token"
        )
        or st.query_params.get("dt")
    )

    if token:

        DRIVER_SESSIONS.pop(
            token,
            None
        )

    st.session_state.driver = None
    st.session_state.driver_id = None
    st.session_state.driver_token = None
    st.session_state.driver_order_id = None
    st.session_state.driver_step = "order"

    if "dt" in st.query_params:
        del st.query_params["dt"]


def restore_driver_session():

    token = (
        st.session_state.get(
            "driver_token"
        )
        or st.query_params.get("dt")
    )

    sess = (
        DRIVER_SESSIONS.get(token)
        if token
        else None
    )

    if (
        sess
        and now_kst()
        < parse_dt(sess["expires_at"])
    ):

        st.session_state.driver_token = token
        st.session_state.driver_id = sess["driver_id"]
        st.session_state.driver = DRIVERS[
            sess["driver_id"]
        ]

        return True

    end_driver_session()

    return False


def driver_session_left():

    sess = DRIVER_SESSIONS.get(
        st.session_state.get(
            "driver_token"
        )
    )

    if not sess:
        return ""

    left = int(
        (
            parse_dt(sess["expires_at"])
            - now_kst()
        ).total_seconds()
    )

    hours, rest = divmod(
        max(left, 0),
        3600
    )

    return (
        f"{hours}시간 "
        f"{rest // 60}분"
    )


# =========================================================
# 이메일
# =========================================================

def send_order_email(
    order_id,
    order,
    qr_url,
    qr_image
):

    try:

        sender = (
            st.secrets["email"]["sender"]
        )

        app_pw = (
            st.secrets["email"]["app_password"]
        )

        host = st.secrets["email"].get(
            "host",
            "smtp.gmail.com"
        )

        port = int(
            st.secrets["email"].get(
                "port",
                465
            )
        )

    except Exception:

        return (
            False,
            "이메일 설정(secrets)이 없습니다."
        )

    driver_name = DRIVERS[
        order["driver_id"]
    ]["name"]

    msg = EmailMessage()

    msg["Subject"] = (
        f"[배송 확인 시스템] "
        f"주문 {order_id} 등록 안내"
    )

    msg["From"] = sender
    msg["To"] = order["buyer_email"]

    msg.set_content(

        f"{order['buyer']}님, "
        "주문이 정상적으로 등록되었습니다.\n\n"

        f"■ 주문번호: {order_id}\n"

        f"■ 구매 물품: "
        f"{order['product']}\n"

        f"■ 수량: "
        f"{order['quantity']}개\n"

        f"■ 가격: "
        f"{order['price']:,}원\n"

        f"■ 배송 주소: "
        f"{order['address']}\n"

        f"■ 담당 기사: "
        f"{driver_name}\n"

        f"■ 배송 상태: "
        f"{order['status']}\n"

        f"■ 정보 공개시간: "
        f"배송 완료 후 "
        f"{fmt_minutes(order['expire_minutes'])}\n\n"

        "아래 링크에서 주문을 조회할 수 있습니다.\n"

        f"{qr_url}\n\n"

        "※ 비밀번호는 주문 시 설정하신 값입니다."
    )

    msg.add_attachment(

        qr_image,

        maintype="image",

        subtype="png",

        filename=f"{order_id}_QR_link.png"

    )

    try:

        with smtplib.SMTP_SSL(
            host,
            port,
            timeout=15
        ) as server:

            server.login(
                sender,
                app_pw
            )

            server.send_message(
                msg
            )

        return True, ""

    except Exception as e:

        return False, str(e)


# =========================================================
# 세션 초기화
# =========================================================

if "page" not in st.session_state:
    st.session_state.page = "menu"

if "driver" not in st.session_state:
    st.session_state.driver = None

if "generated" not in st.session_state:
    st.session_state.generated = None

if "driver_order_id" not in st.session_state:
    st.session_state.driver_order_id = None

if "manage_found" not in st.session_state:
    st.session_state.manage_found = []

if "driver_id" not in st.session_state:
    st.session_state.driver_id = None

if "driver_token" not in st.session_state:
    st.session_state.driver_token = None

if "driver_step" not in st.session_state:
    st.session_state.driver_step = "order"

if "driver_last_scan_ts" not in st.session_state:
    st.session_state.driver_last_scan_ts = None

if "buyer_oid" not in st.session_state:
    st.session_state.buyer_oid = None

if "buyer_step" not in st.session_state:
    st.session_state.buyer_step = "login"

if "last_scan_ts" not in st.session_state:
    st.session_state.last_scan_ts = None

if "cam_key" not in st.session_state:
    st.session_state.cam_key = 0


def reset_buyer():

    st.session_state.buyer_oid = None
    st.session_state.buyer_step = "login"


# =========================================================
# 메인
# =========================================================

st.title(
    "배송 확인 시스템"
)


# =========================================================
# 메뉴
# =========================================================

if st.session_state.page == "menu":

    st.subheader("메뉴")

    col1, col2, col3 = st.columns(3)

    with col1:

        if st.button(
            "배송기사",
            use_container_width=True
        ):

            if restore_driver_session():

                st.session_state.driver_step = "order"
                st.session_state.driver_order_id = None

                go("driver_dashboard")

            go("driver_login")


    with col2:

        if st.button(
            "구매자",
            use_container_width=True
        ):

            reset_buyer()

            go("buyer_login")


    with col3:

        if st.button(
            "판매자",
            use_container_width=True
        ):

            go("seller_menu")


    st.divider()

    if st.button(
        "주문번호 & 비밀번호 찾기",
        use_container_width=True
    ):

        go("find_order")


# =========================================================
# 주문 찾기
# =========================================================

elif st.session_state.page == "find_order":

    st.subheader(
        "주문번호 & 비밀번호 찾기"
    )

    st.write(
        "주문할 때 입력한 이름과 "
        "이메일을 입력해주세요."
    )

    with st.form(
        "find_order_form"
    ):

        find_name = st.text_input(
            "구매자 이름"
        )

        find_email = st.text_input(
            "구매자 이메일"
        )

        find = st.form_submit_button(
            "주문번호 & 비밀번호 찾기",
            use_container_width=True
        )

    if find:

        find_name = find_name.strip()
        find_email = (
            find_email
            .strip()
            .lower()
        )

        if not find_name or not find_email:

            st.warning(
                "이름과 이메일을 모두 입력해주세요."
            )

        else:

            result = (
                supabase
                .table("orders")
                .select("*")
                .eq("buyer", find_name)
                .eq("buyer_email", find_email)
                .execute()
            )

            found_orders = (
                result.data or []
            )

            if found_orders:

                st.success(
                    "주문을 찾았습니다."
                )

                for order in found_orders:

                    st.write(
                        f"### {order['order_id']}"
                    )

                    st.write(
                        "**비밀번호:**",
                        order["pw"]
                    )

                    st.write(
                        "**배송상태:**",
                        status_of(order)
                    )

                    st.write(
                        "**구매 물품:**",
                        order["product"]
                    )

                    st.divider()

            else:

                st.error(
                    "입력한 정보와 "
                    "일치하는 주문이 없습니다."
                )


    if st.button(
        "메인 메뉴로",
        use_container_width=True
    ):

        go("menu")


# =========================================================
# 판매자
# =========================================================

elif st.session_state.page == "seller":

    st.subheader(
        "판매자 주문 등록 및 QR코드 생성"
    )

    with st.form(
        "seller_form"
    ):

        order_id = st.text_input(
            "주문번호",
            placeholder="ORD003"
        )

        buyer = st.text_input(
            "구매자 이름",
            placeholder="홍길동"
        )

        buyer_email = st.text_input(
            "구매자 이메일",
            placeholder="example@email.com"
        )

        address = st.text_input(
            "배송 주소",
            placeholder="00시 00구 000로 123"
        )

        product = st.text_input(
            "구매 물품",
            placeholder="무선 이어폰"
        )

        quantity = st.number_input(
            "수량",
            min_value=1,
            value=1
        )

        price = st.number_input(
            "가격",
            min_value=0,
            step=1000
        )

        password = st.text_input(
            "구매자 비밀번호",
            type="password"
        )

        assigned_driver = st.selectbox(
            "담당 배송기사",
            list(DRIVERS),
            format_func=lambda d:
                f"{d} ({DRIVERS[d]['name']})"
        )

        expire_option = st.selectbox(
            "정보 공개시간",
            list(EXPIRE_MINUTES),
            index=5
        )

        app_url = st.text_input(
            "QR생성용 링크",
            value="https://service.streamlit.app"
        )

        submitted = st.form_submit_button(
            "주문 등록 및 QR코드 생성",
            use_container_width=True
        )


    if submitted:

        order_id = (
            order_id
            .strip()
            .upper()
        )

        buyer = buyer.strip()
        buyer_email = buyer_email.strip()
        address = address.strip()
        product = product.strip()
        password = password.strip()
        app_url = (
            app_url
            .strip()
            .rstrip("/")
        )

        if not all([
            order_id,
            buyer,
            buyer_email,
            address,
            product,
            password,
            app_url
        ]):

            st.error(
                "모든 항목을 입력해주세요."
            )

        elif db_get_order(order_id):

            st.error(
                "이미 등록된 주문번호입니다."
            )

        else:

            token = secrets.token_urlsafe(
                16
            )

            order = {

                "order_id": order_id,

                "pw": password,

                "buyer": buyer,

                "buyer_email": buyer_email,

                "address": address,

                "location": address,

                "product": product,

                "quantity": int(quantity),

                "price": int(price),

                "driver_id": assigned_driver,

                "status": "배송준비",

                "token": token,

                "expire_minutes":
                    EXPIRE_MINUTES[
                        expire_option
                    ],

                "started_at": None,

                "completed_at": None,

                "expires_at": None,

                "created_at":
                    iso_now(),

            }


            try:

                saved_order = db_insert_order(
                    order
                )

            except Exception as e:

                st.error(
                    f"DB 저장 실패: {e}"
                )

                saved_order = None


            if saved_order:

                qr_url = (
                    f"{app_url}"
                    f"?order={quote(order_id)}"
                    f"&token={quote(token)}"
                )

                qr_text = build_qr_text(
                    order_id,
                    saved_order
                )

                st.session_state.generated = {

                    "order_id":
                        order_id,

                    "url":
                        qr_url,

                    "image":
                        make_qr(qr_url),

                    "text":
                        qr_text,

                    "text_image":
                        make_qr(qr_text),

                }

                st.success(
                    "주문이 Supabase DB에 "
                    "정상적으로 저장되었습니다."
                )


                with st.spinner(
                    "구매자 이메일로 "
                    "안내 메일을 보내는 중..."
                ):

                    ok, err = send_order_email(

                        order_id,

                        saved_order,

                        qr_url,

                        st.session_state.generated[
                            "image"
                        ]

                    )

                if ok:

                    st.success(
                        f"{buyer_email} 로 "
                        "안내 메일을 보냈습니다."
                    )

                else:

                    st.warning(
                        "주문은 등록되었지만 "
                        f"메일 발송에 실패했습니다: {err}"
                    )


    generated = (
        st.session_state.generated
    )

    if generated:

        order = db_get_order(
            generated["order_id"]
        )

        if order:

            st.divider()

            st.write(
                "### 생성 결과"
            )

            st.write(
                "**주문번호:**",
                generated["order_id"]
            )

            st.write(
                "**구매자:**",
                order["buyer"]
            )

            st.write(
                "**주소:**",
                order["address"]
            )

            st.write(
                "**배송 위치:**",
                order["location"]
            )

            st.write(
                "**담당 기사:**",
                f'{order["driver_id"]} '
                f'({DRIVERS[order["driver_id"]]["name"]})'
            )

            show_extra(order)

            st.write(
                "**상태:**",
                status_of(order)
            )


            col1, col2 = st.columns(2)


            with col1:

                st.image(
                    generated["image"],
                    caption="QR① 주문 조회용",
                    use_container_width=True
                )

                st.download_button(
                    "QR① 저장",
                    generated["image"],
                    file_name=
                        f'{generated["order_id"]}_QR_link.png',
                    mime="image/png",
                    use_container_width=True
                )


            with col2:

                st.image(
                    generated["text_image"],
                    caption="QR② 택배 확인용",
                    use_container_width=True
                )

                st.download_button(
                    "QR② 저장",
                    generated["text_image"],
                    file_name=
                        f'{generated["order_id"]}_QR_text.png',
                    mime="image/png",
                    use_container_width=True
                )


            with st.expander(
                "QR① 접속 주소"
            ):

                st.code(
                    generated["url"]
                )


            with st.expander(
                "QR② 저장된 글 내용"
            ):

                st.code(
                    generated["text"]
                )


    if st.button(
        "판매자 메뉴로",
        use_container_width=True
    ):

        go("seller_menu")


# =========================================================
# 판매자 메뉴
# =========================================================

elif st.session_state.page == "seller_menu":

    st.subheader("판매자")

    col1, col2 = st.columns(2)

    with col1:

        if st.button(
            "주문 등록",
            use_container_width=True
        ):

            go("seller")


    with col2:

        if st.button(
            "배송 관리",
            use_container_width=True
        ):

            st.session_state.manage_found = []

            go("seller_manage")


    st.divider()

    if st.button(
        "메인 메뉴로",
        use_container_width=True
    ):

        go("menu")


# =========================================================
# 배송 관리
# =========================================================

elif st.session_state.page == "seller_manage":

    st.subheader("배송 관리")

    st.write(
        "구매자의 이름과 배송 주소를 입력해주세요."
    )

    with st.form(
        "manage_form"
    ):

        m_name = st.text_input(
            "구매자 이름"
        )

        m_addr = st.text_input(
            "배송 주소"
        )

        m_find = st.form_submit_button(
            "주문 조회",
            use_container_width=True
        )


    if m_find:

        name = m_name.strip()
        addr = " ".join(
            m_addr.split()
        )

        if not name or not addr:

            st.session_state.manage_found = []

            st.warning(
                "이름과 주소를 모두 입력해주세요."
            )

        else:

            result = (
                supabase
                .table("orders")
                .select("*")
                .eq("buyer", name)
                .execute()
            )

            candidates = (
                result.data or []
            )

            st.session_state.manage_found = [

                o["order_id"]

                for o in candidates

                if " ".join(
                    o.get("address", "").split()
                ) == addr

            ]

            if not st.session_state.manage_found:

                st.error(
                    "입력한 정보와 "
                    "일치하는 주문이 없습니다."
                )


    for oid in (
        st.session_state.manage_found
    ):

        order = db_get_order(oid)

        if not order:
            continue

        st.divider()

        st.write(
            f"### {oid}"
        )

        st.write(
            "**구매자:**",
            order["buyer"]
        )

        st.write(
            "**주소:**",
            order["address"]
        )

        st.write(
            "**담당 기사:**",
            f'{order["driver_id"]} '
            f'({DRIVERS[order["driver_id"]]["name"]})'
        )

        show_extra(order)

        st.write(
            "**상태:**",
            status_of(order)
        )


        if order["status"] == "배송준비":

            if st.button(
                "배송시작",
                key=f"start_{oid}",
                type="primary",
                use_container_width=True
            ):

                try:

                    db_update_order(

                        oid,

                        {
                            "status":
                                "배송 시작",

                            "started_at":
                                iso_now()
                        }

                    )

                    st.rerun()

                except Exception as e:

                    st.error(
                        f"배송 시작 처리 실패: {e}"
                    )


        elif order["status"] == "배송 시작":

            st.info(
                "배송이 시작되었습니다."
            )


    st.divider()

    if st.button(
        "판매자 메뉴로",
        use_container_width=True
    ):

        st.session_state.manage_found = []

        go("seller_menu")


# =========================================================
# 배송기사 로그인
# =========================================================

elif st.session_state.page == "driver_login":

    st.subheader(
        "배송기사 로그인"
    )

    st.caption(
        f"기사번호와 첫 번째 배송 주문번호로 로그인하면 "
        f"{DRIVER_SESSION_HOURS}시간 동안 다시 로그인하지 않아도 됩니다."
    )

    driver_id = st.text_input(
        "기사번호",
        placeholder="D001"
    )

    first_order = st.text_input(
        "첫 번째 주문번호",
        value=st.query_params.get(
            "order",
            ""
        ),
        placeholder="ORD003"
    )


    col1, col2 = st.columns(2)


    with col1:

        if st.button(
            "로그인",
            type="primary",
            use_container_width=True
        ):

            did = (
                driver_id
                .strip()
                .upper()
            )

            oid = (
                first_order
                .strip()
                .upper()
            )

            order = db_get_order(
                oid
            )


            if (
                did not in DRIVERS
                or not order
                or order.get("driver_id")
                != did
            ):

                st.error(
                    "인증 실패"
                )

            elif expired(order):

                show_expired()

            else:

                create_driver_session(
                    did
                )

                st.session_state.driver_order_id = oid

                st.session_state.driver_step = "scan"

                st.session_state.driver_last_scan_ts = None

                go(
                    "driver_dashboard"
                )


    with col2:

        if st.button(
            "취소",
            use_container_width=True
        ):

            go("menu")


# =========================================================
# 배송기사
# =========================================================

elif st.session_state.page == "driver_dashboard":

    if not restore_driver_session():

        go("driver_login")


    driver = st.session_state.driver

    st.subheader(
        f'배송기사 - {driver["name"]}님'
    )

    st.caption(
        f"로그인 유지 시간: "
        f"{driver_session_left()} 남음"
    )


    step = (
        st.session_state.driver_step
    )


    if step == "order":

        order_id = st.text_input(
            "주문번호",
            value=st.query_params.get(
                "order",
                ""
            ),
            placeholder="ORD003"
        )


        col1, col2 = st.columns(2)


        with col1:

            start = st.button(
                "QR 스캔",
                type="primary",
                use_container_width=True
            )


        with col2:

            if st.button(
                "로그아웃",
                use_container_width=True
            ):

                end_driver_session()

                go("menu")


        if st.button(
            "메인 메뉴로",
            use_container_width=True
        ):

            go("menu")


        if start:

            oid = (
                order_id
                .strip()
                .upper()
            )

            order = db_get_order(
                oid
            )


            if not order:

                st.warning(
                    "주문이 없습니다."
                )

            elif (
                order.get("driver_id")
                != st.session_state.driver_id
            ):

                st.error(
                    "본인에게 배정된 주문이 아닙니다."
                )

            elif expired(order):

                show_expired()

            else:

                st.session_state.driver_order_id = oid

                st.session_state.driver_step = "scan"

                st.session_state.driver_last_scan_ts = None

                st.rerun()


    elif step == "scan":

        oid = (
            st.session_state.driver_order_id
        )

        st.write(
            f"**주문번호:** {oid}"
        )

        st.write(
            "송장에 붙은 "
            "**주문정보 QR코드(QR②)**를 "
            "후면 카메라의 네모 칸 안에 갖다 대세요."
        )


        if st.button(
            "주문번호 다시 입력",
            use_container_width=True
        ):

            st.session_state.driver_step = "order"

            st.rerun()


        if st.button(
            "메인 메뉴로",
            use_container_width=True
        ):

            st.session_state.driver_step = "order"

            st.session_state.driver_order_id = None

            go("menu")


        scan = qr_scanner(
            key="driver_scan",
            default=None
        )


        if (
            scan
            and scan.get("ts")
            != st.session_state.driver_last_scan_ts
        ):

            st.session_state.driver_last_scan_ts = scan.get(
                "ts"
            )


            if verify_parcel(
                scan.get("text", ""),
                oid
            ):

                st.session_state.driver_step = "info"

                st.rerun()

            else:

                st.toast(
                    "입력한 주문의 송장이 아닙니다.",
                    icon="❌"
                )


    elif step == "info":

        oid = (
            st.session_state.driver_order_id
        )

        order = db_get_order(
            oid
        )


        if (
            order
            and order.get("driver_id")
            != st.session_state.driver_id
        ):

            st.session_state.driver_step = "order"

            st.error(
                "본인에게 배정된 주문이 아닙니다."
            )


        elif (
            not order
            or expired(order)
        ):

            st.session_state.driver_step = "order"

            show_expired()


        else:

            st.success(
                "송장 확인 완료"
            )

            st.write(
                "### 배송 정보"
            )

            st.write(
                "**주문번호:**",
                oid
            )

            st.write(
                "**수령인:**",
                order["buyer"]
            )

            st.write(
                "**주소:**",
                order["address"]
            )

            st.write(
                "**배송 위치:**",
                order["location"]
            )

            show_extra(order)

            st.write(
                "**상태:**",
                status_of(order)
            )


            map_url = (
                "https://map.kakao.com/link/search/"
                + quote(
                    order["address"]
                )
            )

            st.link_button(
                "카카오맵에서 보기",
                map_url,
                use_container_width=True
            )


            if order["status"] != "배송완료":

                if st.button(
                    "배송 완료",
                    type="primary",
                    use_container_width=True
                ):

                    now = now_kst()

                    updates = {

                        "status":
                            "배송완료",

                        "completed_at":
                            now.isoformat(),

                    }


                    if order.get(
                        "expire_minutes"
                    ):

                        updates[
                            "expires_at"
                        ] = (

                            now
                            + timedelta(
                                minutes=int(
                                    order[
                                        "expire_minutes"
                                    ]
                                )
                            )

                        ).isoformat()


                    try:

                        db_update_order(
                            oid,
                            updates
                        )

                        st.success(
                            "배송 완료 처리되었습니다."
                        )

                        st.rerun()

                    except Exception as e:

                        st.error(
                            f"배송 완료 처리 실패: {e}"
                        )


            else:

                st.success(
                    "배송이 완료된 주문입니다."
                )


            if st.button(
                "메인 메뉴로",
                use_container_width=True
            ):

                st.session_state.driver_step = "order"

                st.session_state.driver_order_id = None

                go("menu")


            if st.button(
                "로그아웃",
                use_container_width=True
            ):

                end_driver_session()

                go("menu")


# =========================================================
# 구매자
# =========================================================

elif st.session_state.page == "buyer_login":

    st.subheader(
        "구매자 조회"
    )

    step = (
        st.session_state.buyer_step
    )


    if step == "login":

        order_id = st.text_input(
            "주문번호",
            value=st.query_params.get(
                "order",
                ""
            )
        )

        password = st.text_input(
            "비밀번호",
            type="password"
        )


        col1, col2 = st.columns(2)


        with col1:

            find = st.button(
                "QR로 찾기",
                type="primary",
                use_container_width=True
            )


        with col2:

            if st.button(
                "취소",
                use_container_width=True
            ):

                go("menu")


        if find:

            oid = (
                order_id
                .strip()
                .upper()
            )

            order = db_get_order(
                oid
            )


            if (
                not order
                or order["pw"] != password
            ):

                st.error(
                    "인증 실패"
                )

            elif expired(order):

                show_expired()

            else:

                st.session_state.buyer_oid = oid

                st.session_state.buyer_step = "scan"

                st.session_state.cam_key += 1

                st.rerun()


    elif step == "scan":

        my_oid = (
            st.session_state.buyer_oid
        )

        st.write(
            "택배에 붙은 "
            "**주문정보 QR코드(QR②)**를 "
            "후면 카메라의 네모 칸 안에 갖다 대기만 하세요."
        )


        if st.button(
            "처음으로",
            use_container_width=True
        ):

            reset_buyer()

            st.rerun()


        scan = qr_scanner(
            key="qr_scan",
            default=None
        )


        if (
            scan
            and scan.get("ts")
            != st.session_state.last_scan_ts
        ):

            st.session_state.last_scan_ts = scan.get(
                "ts"
            )


            if verify_parcel(
                scan.get("text", ""),
                my_oid
            ):

                st.session_state.buyer_step = "result"

                st.rerun()

            else:

                st.toast(
                    "고객님의 택배가 아닙니다."
                )


    elif step == "result":

        my_oid = (
            st.session_state.buyer_oid
        )

        order = db_get_order(
            my_oid
        )


        if (
            not order
            or expired(order)
        ):

            reset_buyer()

            show_expired()


        else:

            st.success(
                "고객님의 택배가 맞습니다!"
            )

            st.write(
                "### 배송 정보"
            )

            st.write(
                "**주문번호:**",
                my_oid
            )

            st.write(
                "**수령인:**",
                order["buyer"]
            )

            masked = (
                " ".join(
                    order["address"]
                    .split()[:3]
                )
                + " ***"
            )

            st.write(
                "**주소:**",
                masked
            )

            show_extra(order)

            st.write(
                "**상태:**",
                status_of(order)
            )


        if st.button(
            "완료 (메인 메뉴로)",
            use_container_width=True
        ):

            reset_buyer()

            go("menu")
