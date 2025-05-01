import pymysql
from typing import Tuple, Optional, List, Any
from pymysql.connections import Connection
from pymysql.cursors import Cursor

def parse_price(text: str) -> float:
    """
    문자열에서 가격을 파싱하여 float로 변환합니다.
    
    Args:
        text (str): 파싱할 가격 문자열 (예: "1,234.56$")
        
    Returns:
        float: 파싱된 가격 값. 파싱 실패 시 0.0 반환
    """
    try:
        return float(text.replace(',', '').replace('$', ''))
    except (ValueError, AttributeError):
        return 0.0

def parse_percent(text: str) -> float:
    """
    문자열에서 퍼센트 값을 파싱하여 float로 변환합니다.
    
    Args:
        text (str): 파싱할 퍼센트 문자열 (예: "+12.34%")
        
    Returns:
        float: 파싱된 퍼센트 값. 파싱 실패 시 0.0 반환
    """
    try:
        return float(text.replace('%', '').replace('+', '').replace(',', ''))
    except (ValueError, AttributeError):
        return 0.0

def is_data_exist(conn: Connection, cursor: Cursor, values: List[Any]) -> bool:
    """
    데이터베이스에 동일한 데이터가 존재하는지 확인합니다.
    
    Args:
        conn (Connection): 데이터베이스 연결 객체
        cursor (Cursor): 데이터베이스 커서 객체
        values (List[Any]): 확인할 데이터 값 리스트
        
    Returns:
        bool: 데이터가 존재하지 않으면 True, 존재하면 False
    """
    check_query = """
    SELECT COUNT(*) FROM 삼성가스 
    WHERE 작성날짜 = %s AND 한국시간 = %s AND 선물구분 = %s
    """
    try:
        cursor.execute(check_query, (values[0], values[1], values[2]))
        exists = cursor.fetchone()[0] > 0
        return not exists
    except Exception as e:
        print(f"데이터 중복 확인 중 오류 발생: {str(e)}")
        return False

def insert_energy_data(conn: Connection, cursor: Cursor, values: List[Any]) -> bool:
    """
    에너지 데이터를 데이터베이스에 삽입합니다.
    
    Args:
        conn (Connection): 데이터베이스 연결 객체
        cursor (Cursor): 데이터베이스 커서 객체
        values (List[Any]): 삽입할 데이터 값 리스트
        
    Returns:
        bool: 삽입 성공 여부
    """
    query = """
    INSERT INTO 삼성가스 
    (작성날짜, 한국시간, 선물구분, 선물가, 월물, 선물변동률, 환율, 환율변동률, 지표가치, 지표가치변동률) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    try:
        if is_data_exist(conn, cursor, values):
            cursor.execute(query, values)
            conn.commit()
            return True
        else:
            print("중복 데이터 발견 - 삽입 건너뛰기")
            return False
    except Exception as e:
        print(f"데이터 삽입 중 오류 발생: {str(e)}")
        conn.rollback()
        return False

def connect(host: str = '', user: str = '', password: str = '', db: str = '') -> Tuple[Optional[Connection], Optional[Cursor]]:
    """
    MySQL 데이터베이스에 연결을 시도합니다.
    
    Args:
        host (str): 데이터베이스 호스트 주소 (예: 'localhost' 또는 IP 주소)
        user (str): 데이터베이스 사용자 이름
        password (str): 데이터베이스 비밀번호
        db (str): 데이터베이스 이름
        
    Returns:
        Tuple[Optional[Connection], Optional[Cursor]]: 
            (데이터베이스 연결 객체, 커서 객체) 또는 (None, None)
    """
    conn = None
    cursor = None
    try:
        # 필수 설정값 검증
        if not all([host, user, password, db]):
            print("데이터베이스 연결 설정이 불완전합니다. 모든 설정값을 입력해주세요.")
            return None, None
            
        conn = pymysql.connect(
            host=host,
            user=user,
            password=password,
            db=db,
            charset='utf8'
        )
        cursor = conn.cursor()
        print("데이터베이스 연결 성공")
    except pymysql.Error as e:
        print(f"MySQL 연결 실패: {str(e)}")
    except Exception as e:
        print(f"예상치 못한 오류 발생: {str(e)}")
    
    return conn, cursor 
