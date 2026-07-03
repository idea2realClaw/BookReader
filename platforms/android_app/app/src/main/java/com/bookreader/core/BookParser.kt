package com.bookreader.core

/**
 * 书籍解析器接口 - Kotlin 版本
 * 与 Python core 模块的 BookParser 抽象基类对应
 */
interface BookParser {
    fun parse(file_path: String): Book
    fun getPage(page_num: Int): Page
    fun getTotalPages(): Int
}

/**
 * TXT 文件解析器
 */
class TXTParser(private val filePath: String, private val charsPerPage: Int = 2000) : BookParser {
    private var content: String = ""
    private var pages: List<String> = listOf()
    
    override fun parse(file_path: String): Book {
        val path = file_path.ifEmpty { filePath }
        
        // 读取文件内容
        val file = java.io.File(path)
        content = file.readText(Charsets.UTF_8)
        
        // 计算分页
        pages = content.chunked(charsPerPage)
        
        // 提取标题
        val lines = content.lines().map { it.trim() }.filter { it.isNotEmpty() }
        val title = if (lines.isNotEmpty()) lines[0] else file.nameWithoutExtension
        
        return Book(
            id = file.nameWithoutExtension,
            title = title,
            author = "",
            path = path,
            format = "txt",
            totalPages = pages.size
        )
    }
    
    override fun getPage(page_num: Int): Page {
        if (page_num in 0 until pages.size) {
            return Page(
                pageNum = page_num,
                content = pages[page_num]
            )
        }
        throw IndexOutOfBoundsException("Page $page_num out of range")
    }
    
    override fun getTotalPages(): Int {
        return pages.size
    }
}

/**
 * PDF 文件解析器
 */
class PDFParser(private val filePath: String) : BookParser {
    private var texts: List<String> = listOf()
    
    override fun parse(file_path: String): Book {
        val path = file_path.ifEmpty { filePath }
        
        // TODO: 使用 Android PDF 库解析
        // 临时返回空数据
        
        return Book(
            id = java.io.File(path).nameWithoutExtension,
            title = java.io.File(path).nameWithoutExtension,
            author = "",
            path = path,
            format = "pdf",
            totalPages = 0
        )
    }
    
    override fun getPage(page_num: Int): Page {
        return Page(pageNum = page_num, content = "")
    }
    
    override fun getTotalPages(): Int {
        return texts.size
    }
}

/**
 * 书籍仓库 - 管理书籍列表和阅读进度
 */
class BookRepository(private val context: android.content.Context) {
    private val storagePath = "bookshelf.json"
    private val books: MutableList<Book> = mutableListOf()
    
    init {
        load()
    }
    
    fun addBook(book: Book) {
        books.add(book)
        save()
    }
    
    fun removeBook(bookId: String) {
        books.removeAll { it.id == bookId }
        save()
    }
    
    fun getBook(bookId: String): Book? {
        return books.find { it.id == bookId }
    }
    
    fun getAllBooks(): List<Book> {
        return books.toList()
    }
    
    fun updateProgress(bookId: String, currentPage: Int) {
        getBook(bookId)?.let {
            it.currentPage = currentPage
            save()
        }
    }
    
    fun addBookmark(bookId: String, pageNum: Int) {
        getBook(bookId)?.let {
            if (!it.bookmarks.contains(pageNum)) {
                it.bookmarks.add(pageNum)
                save()
            }
        }
    }
    
    private fun save() {
        // TODO: 保存到 SharedPreferences 或 JSON 文件
    }
    
    private fun load() {
        // TODO: 从 SharedPreferences 或 JSON 文件加载
    }
}

/**
 * 工厂函数 - 根据文件类型创建解析器
 */
fun createParser(file_path: String): BookParser {
    val extension = file_path.substringAfterLast('.', "")
    
    return when (extension.lowercase()) {
        "txt" -> TXTParser(file_path)
        "pdf" -> PDFParser(file_path)
        "epub" -> throw IllegalArgumentException("EPUB not yet supported")
        else -> throw IllegalArgumentException("Unsupported format: $extension")
    }
}
