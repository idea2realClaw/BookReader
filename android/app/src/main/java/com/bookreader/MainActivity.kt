package com.bookreader

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.bookreader.databinding.ActivityMainBinding
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val books = mutableListOf<Map<String, Any>>()

    private val filePicker = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        uri?.let { openBook(it) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Initialize Chaquopy Python
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupUI()
        loadBooks()
    }

    private fun setupUI() {
        binding.fabAdd.setOnClickListener {
            openFilePicker()
        }
    }

    private fun openFilePicker() {
        filePicker.launch(arrayOf(
            "application/pdf",
            "application/epub+zip",
            "text/plain"
        ))
    }

    private fun openBook(uri: Uri) {
        try {
            val py = Python.getInstance()
            val core = py.getModule("core")
            
            // Call Python function to parse book
            val filePath = uri.toString()
            val parser = core.callAttr("create_parser", filePath)
            val book = parser.callAttr("parse", filePath)
            
            // Convert Python object to Kotlin Map
            val bookMap = mapOf(
                "id" to book["id"].toString(),
                "title" to book["title"].toString(),
                "author" to book["author"].toString(),
                "path" to book["path"].toString(),
                "format" to book["format"].toString(),
                "total_pages" to book["total_pages"].toInt(),
                "current_page" to book["current_page"].toInt()
            )
            
            books.add(bookMap)
            updateBookList()
            
            // Open reader
            val intent = Intent(this, ReaderActivity::class.java).apply {
                putExtra("book_path", filePath)
                putExtra("book_type", bookMap["format"])
            }
            startActivity(intent)
            
        } catch (e: Exception) {
            Toast.makeText(this, "Error: ${e.message}", Toast.LENGTH_LONG).show()
            e.printStackTrace()
        }
    }

    private fun loadBooks() {
        try {
            val py = Python.getInstance()
            val core = py.getModule("core")
            val repo = core.callAttr("BookRepository")
            val booksList = repo.callAttr("books")
            
            // Convert Python list to Kotlin
            for (i in 0 until booksList.len()) {
                val book = booksList[i]
                books.add(mapOf(
                    "id" to book["id"].toString(),
                    "title" to book["title"].toString(),
                    "format" to book["format"].toString(),
                    "total_pages" to book["total_pages"].toInt()
                ))
            }
            
            updateBookList()
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun updateBookList() {
        // TODO: Update RecyclerView adapter
        Toast.makeText(this, "Books loaded: ${books.size}", Toast.LENGTH_SHORT).show()
    }

    private fun saveBooks() {
        try {
            val py = Python.getInstance()
            val core = py.getModule("core")
            val repo = core.callAttr("BookRepository")
            repo.callAttr("save")
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
}
